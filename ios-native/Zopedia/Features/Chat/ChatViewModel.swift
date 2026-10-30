import Foundation
import Observation
import os
import ZopediaKit

struct ChatBranchInfo: Equatable {
    let index: Int
    let count: Int
}

@MainActor
@Observable
final class ChatViewModel {
    private static let logger = Logger(subsystem: "com.zopedia.client", category: "chat")

    let thread: ChatThread

    /// Every stored message, including alternate branches.
    private(set) var allMessages: [ChatMessage] = []
    /// The single root-to-leaf path currently displayed.
    private(set) var messages: [ChatMessage] = []
    private(set) var liveMessage: ChatMessage?
    private(set) var liveRevision = 0
    private(set) var toolStatus: String?
    private(set) var toolStatusSince: Date?
    private(set) var isStreaming = false
    private(set) var isLoading = true
    private(set) var errorMessage: String?
    private(set) var title: String
    private(set) var needsRecovery = false

    var draft = ""

    var canSend: Bool {
        !isStreaming && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Completed messages plus the in-flight one, in a single list so SwiftUI
    /// keeps the assistant row's identity when the stream finishes.
    var displayMessages: [ChatMessage] {
        var result = messages
        if let liveMessage { result.append(liveMessage) }
        return result
    }

    var userMessages: [ChatMessage] {
        messages.filter { $0.role == .user }
    }

    var lastVisibleAssistantID: String? {
        messages.last(where: { $0.role == .assistant })?.id
    }

    private var savesHistory: Bool {
        (app.permissions?.canSaveChatHistory ?? true) && app.chatOptions.logChatHistory
    }

    private let app: AppEnvironment
    private var isNewThread: Bool
    private var assembler = ChatStreamAssembler()
    private var streamTask: Task<Void, Never>?
    private var publishTask: Task<Void, Never>?
    private var firstUserText: String?
    private var currentUserMessageID: String?
    private var assistantMessageID: String?
    private var assistantCreatedAt = Date()
    private var partialAppended = false
    private var isBackgroundSuspended = false
    private var didAttemptTitle = false
    private var didSaveThread = false
    private var selectedBranches: [String: String] = [:]
    private var streamingParentID: String?
    private let onThreadUpdated: ((ChatThread) -> Void)?

    init(
        thread: ChatThread,
        app: AppEnvironment,
        isNew: Bool,
        onThreadUpdated: ((ChatThread) -> Void)? = nil
    ) {
        self.thread = thread
        self.app = app
        self.isNewThread = isNew
        self.title = thread.title
        self.onThreadUpdated = onThreadUpdated
    }

    func load() async {
        if let cache = app.cache, let cached = await cache.loadThread(thread.id) {
            allMessages = cached.messages.map { $0.normalized() }
            rebuildVisiblePath()
            title = cached.thread.title
        }

        isLoading = messages.isEmpty
        defer { isLoading = false }

        guard !isNewThread, let chat = app.chat else { return }

        do {
            let response = try await chat.getThread(thread.id)
            allMessages = mergeServerMessages(response.messages)
            rebuildVisiblePath()
            title = response.thread.title
            await app.cache?.saveThread(response.thread, messages: allMessages)
            errorMessage = nil
        } catch let error as APIError {
            if case .http(let status, _) = error, status == 404 {
                allMessages = []
                rebuildVisiblePath()
            } else if error != .cancelled {
                errorMessage = errorText(error)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func send(
        imageBase64: String? = nil,
        imageData: Data? = nil,
        imageName: String? = nil,
        extractedText: String? = nil,
        attachmentName: String? = nil
    ) async {
        let typed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        var pieces: [String] = []
        if !typed.isEmpty {
            pieces.append(typed)
        }
        if let extractedText, !extractedText.isEmpty {
            let label = attachmentName.map { "[PDF: \($0)]" } ?? "[PDF]"
            pieces.append("\(label)\n\(extractedText)")
        }
        var contentText = pieces.joined(separator: "\n\n")
        if contentText.isEmpty, imageBase64 != nil {
            contentText = "[image attachment]"
        }

        guard !contentText.isEmpty,
              !isStreaming,
              let client = app.client,
              let chat = app.chat else {
            return
        }

        draft = ""
        errorMessage = nil

        var localImageName: String?
        if let imageData, let imageName {
            do {
                try AttachmentProcessor.save(
                    imageData,
                    named: imageName,
                    in: app.cacheRoot.appendingPathComponent("attachments", isDirectory: true)
                )
                localImageName = imageName
            } catch {
                errorMessage = "Could not save the image locally: \(errorText(error))"
            }
        }

        let parentID = messages.last?.id
        let userMessage = ChatMessage(
            id: UUID().uuidString,
            role: .user,
            content: .text(contentText),
            parentID: parentID,
            createdAt: Date(),
            localImageName: localImageName
        )
        allMessages.append(userMessage)
        if let parentID {
            selectedBranches[parentID] = userMessage.id
        }
        rebuildVisiblePath()
        currentUserMessageID = userMessage.id
        if firstUserText == nil {
            firstUserText = typed.isEmpty ? (attachmentName ?? "Attachment") : typed
        }

        if savesHistory {
            do {
                _ = try await chat.appendMessages(
                    threadID: thread.id,
                    title: isNewThread ? title : nil,
                    messages: [userMessage]
                )
                if isNewThread {
                    isNewThread = false
                    didSaveThread = true
                    onThreadUpdated?(snapshot(messageCount: allMessages.count))
                }
            } catch {
                errorMessage = "Could not save your message: \(errorText(error))"
            }
        }

        let outgoing = messages.map {
            OutgoingMessage(role: $0.role.rawValue, content: $0.visibleText)
        }
        startStreaming(
            client: client,
            outgoing: outgoing,
            parentID: userMessage.id,
            imageBase64: imageBase64
        )
    }

    /// Create a sibling response for an assistant message and make it the
    /// selected branch. The previous sibling stays stored and switchable.
    func regenerate(assistantMessageID id: String) async {
        guard !isStreaming,
              let client = app.client,
              let target = allMessages.first(where: { $0.id == id }),
              target.role == .assistant,
              let parentID = target.parentID,
              let parentIndex = messages.firstIndex(where: { $0.id == parentID }) else {
            return
        }

        let outgoing = messages[...parentIndex].map {
            OutgoingMessage(role: $0.role.rawValue, content: $0.visibleText)
        }
        currentUserMessageID = parentID
        startStreaming(
            client: client,
            outgoing: outgoing,
            parentID: parentID,
            imageBase64: nil
        )
    }

    func branchInfo(for message: ChatMessage) -> ChatBranchInfo? {
        guard message.role == .assistant,
              let parent = message.parentID,
              allMessages.contains(where: { $0.id == message.id }) else {
            return nil
        }
        let siblings = allMessages.filter {
            $0.role == .assistant && $0.parentID == parent
        }
        guard siblings.count > 1,
              let index = siblings.firstIndex(where: { $0.id == message.id }) else {
            return nil
        }
        return ChatBranchInfo(index: index, count: siblings.count)
    }

    func selectSibling(of message: ChatMessage, offset: Int) {
        guard !isStreaming,
              let parent = message.parentID else { return }
        let siblings = allMessages.filter {
            $0.role == .assistant && $0.parentID == parent
        }
        guard siblings.count > 1,
              let index = siblings.firstIndex(where: { $0.id == message.id }) else {
            return
        }
        let next = (index + offset + siblings.count) % siblings.count
        selectedBranches[parent] = siblings[next].id
        rebuildVisiblePath()
    }

    func stopWaiting() {
        isBackgroundSuspended = false
        streamTask?.cancel()
        streamTask = nil
    }

    /// Called when the app backgrounds mid-stream. The server keeps generating
    /// and persists the answer; recovery picks it up on return.
    func prepareForBackground() {
        guard isStreaming else { return }
        isBackgroundSuspended = true
        streamTask?.cancel()
    }

    /// Called when the scene becomes active. Polls for a background-completed
    /// answer, or quietly refreshes the thread when nothing was interrupted.
    func recover() async {
        guard !isStreaming, !isNewThread, let chat = app.chat else { return }

        if needsRecovery {
            await pollForRecovery(chat)
        } else {
            await refreshQuietly(chat)
        }
    }

    func answerQuestion(sessionID: String, toolCallID: String, answer: String) async {
        guard let chat = app.chat else { return }
        do {
            try await chat.answerQuestion(
                sessionID: sessionID,
                toolCallID: toolCallID,
                answer: answer
            )
        } catch APIError.conflict {
            errorMessage = "This question is no longer waiting for an answer."
        } catch {
            errorMessage = errorText(error)
        }
    }

    func decideApproval(sessionID: String, toolCallID: String, approve: Bool) async {
        guard let chat = app.chat else { return }
        do {
            try await chat.decideApproval(
                sessionID: sessionID,
                toolCallID: toolCallID,
                approve: approve
            )
        } catch APIError.conflict {
            errorMessage = "This approval is no longer pending. Nothing was placed."
        } catch {
            errorMessage = errorText(error)
        }
    }

    // MARK: - Streaming

    private func startStreaming(
        client: APIClient,
        outgoing: [OutgoingMessage],
        parentID: String,
        imageBase64: String?
    ) {
        let assistantID = UUID().uuidString
        assistantMessageID = assistantID
        currentUserMessageID = parentID
        assistantCreatedAt = Date()
        assembler = ChatStreamAssembler()
        partialAppended = false
        toolStatus = nil
        toolStatusSince = nil
        errorMessage = nil
        isStreaming = true
        streamingParentID = parentID
        selectedBranches[parentID] = assistantID
        rebuildVisiblePath()
        publishNow()

        let options = app.chatOptions
        let request = ChatRequest(
            messages: outgoing,
            enabledTools: options.enabledTools,
            sessionID: thread.id,
            assistantMessageID: assistantID,
            parentID: parentID,
            imageBase64: imageBase64,
            reasoningEffort: options.reasoningEffort,
            enableThinking: options.enableThinking,
            maxTokens: nil
        )

        streamTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let stream = await client.streamChat(request)
                for try await event in stream {
                    self.handle(event)
                    if event == .done { break }
                }
                await self.finish()
            } catch let error as APIError where error == .cancelled {
                self.stopCleanly()
            } catch {
                self.fail(error)
            }
        }
    }

    private func handle(_ event: ChatStreamEvent) {
        assembler.apply(event)

        switch event {
        case .toolStatus(let status):
            if status != toolStatus {
                toolStatusSince = Date()
            }
            toolStatus = status
        case .error(let message):
            errorMessage = message
        case .toolStart, .toolEnd:
            schedulePublish(immediate: true)
        case .textDelta, .reasoningDelta:
            schedulePublish(immediate: false)
        default:
            break
        }
    }

    /// Text deltas arrive far faster than a phone can re-render Markdown. Coalesce
    /// them; tool events publish immediately so cards show up without a lag.
    private func schedulePublish(immediate: Bool) {
        guard assistantMessageID != nil, isStreaming else { return }

        if immediate {
            publishTask?.cancel()
            publishTask = nil
            publishNow()
            return
        }

        guard publishTask == nil else { return }
        publishTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 100_000_000)
            guard !Task.isCancelled, let self else { return }
            self.publishTask = nil
            self.publishNow()
        }
    }

    private func publishNow() {
        guard let assistantMessageID, isStreaming else { return }
        liveMessage = assembler.message(
            id: assistantMessageID,
            parentID: currentUserMessageID,
            createdAt: assistantCreatedAt
        )
        liveRevision &+= 1
    }

    private func cancelScheduledPublish() {
        publishTask?.cancel()
        publishTask = nil
    }

    private func finish() async {
        streamTask = nil
        cancelScheduledPublish()
        isStreaming = false
        streamingParentID = nil
        toolStatus = nil
        toolStatusSince = nil

        guard assembler.hasContent, let assistantMessageID else {
            liveMessage = nil
            rebuildVisiblePath()
            errorMessage = "The model returned an empty response."
            return
        }

        let final = assembler.message(
            id: assistantMessageID,
            parentID: currentUserMessageID,
            createdAt: assistantCreatedAt
        )
        allMessages.append(final)
        if let parent = currentUserMessageID {
            selectedBranches[parent] = assistantMessageID
        }
        liveMessage = nil
        rebuildVisiblePath()

        if savesHistory, let chat = app.chat {
            do {
                _ = try await chat.appendMessages(
                    threadID: thread.id,
                    title: nil,
                    messages: [final]
                )
            } catch {
                errorMessage = "Answer received, but it could not be saved: \(errorText(error))"
            }
        }

        let updated = snapshot(messageCount: allMessages.count)
        await app.cache?.saveThread(updated, messages: allMessages)
        onThreadUpdated?(updated)

        await maybeGenerateTitle(assistantText: final.visibleText)
    }

    private func stopCleanly() {
        streamTask = nil
        cancelScheduledPublish()
        isStreaming = false
        streamingParentID = nil
        toolStatus = nil
        toolStatusSince = nil
        appendPartialIfNeeded()
        rebuildVisiblePath()

        if isBackgroundSuspended {
            isBackgroundSuspended = false
            needsRecovery = true
            errorMessage = "Finishing this response in the background…"
        } else {
            errorMessage = "Stopped waiting. The server may finish this response in the background."
        }
    }

    private func fail(_ error: Error) {
        streamTask = nil
        cancelScheduledPublish()
        isStreaming = false
        streamingParentID = nil
        toolStatus = nil
        toolStatusSince = nil
        appendPartialIfNeeded()
        rebuildVisiblePath()

        if let apiError = error as? APIError, apiError == .streamLost {
            needsRecovery = true
            errorMessage = "Connection lost — the server may finish this response in the background."
        } else {
            errorMessage = errorText(error)
        }
    }

    private func pollForRecovery(_ chat: ChatService) async {
        let delays: [Double] = [1, 2, 4, 8, 16, 16]

        for delay in delays {
            if Task.isCancelled { return }
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))

            do {
                let response = try await chat.getThread(thread.id)
                let merged = mergeServerMessages(response.messages)
                let recovered = hasRecoveredAnswer(in: merged)

                allMessages = merged
                rebuildVisiblePath()
                title = response.thread.title
                await app.cache?.saveThread(response.thread, messages: allMessages)

                if recovered {
                    needsRecovery = false
                    errorMessage = nil
                    return
                }
            } catch APIError.cancelled {
                return
            } catch {
                // Keep polling; the server may still be finishing.
            }
        }

        needsRecovery = false
        errorMessage = "The background response never arrived. Pull to refresh."
    }

    private func refreshQuietly(_ chat: ChatService) async {
        do {
            let response = try await chat.getThread(thread.id)
            allMessages = mergeServerMessages(response.messages)
            rebuildVisiblePath()
            title = response.thread.title
            await app.cache?.saveThread(response.thread, messages: allMessages)
        } catch {
            // Offline or transient failure: keep the cached view.
        }
    }

    /// Merge server messages with local-only metadata (image names) and with
    /// tool cards the server's fallback persistence drops.
    private func mergeServerMessages(_ serverMessages: [ChatMessage]) -> [ChatMessage] {
        var localByID: [String: ChatMessage] = [:]
        for message in allMessages {
            localByID[message.id] = message
        }
        let remoteIDs = Set(serverMessages.map(\.id))

        var merged = serverMessages.map { remote in
            var message = remote.normalized()
            guard let local = localByID[message.id] else { return message }

            if message.localImageName == nil {
                message.localImageName = local.localImageName
            }
            if message.reasoningContent == nil {
                message.reasoningContent = local.reasoningContent
            }

            if case .parts(let localParts) = local.content, case .text(let remoteText) = message.content {
                let localText = local.visibleText
                if remoteText == localText || remoteText.isEmpty {
                    message.content = local.content
                } else if remoteText.count > localText.count {
                    // The server's fallback persisted only text after a background
                    // completion. Keep the local tool positions and put the longer
                    // text where the first text segment was.
                    message.content = Self.replacingText(in: localParts, with: remoteText)
                } else {
                    message.content = local.content
                }
            }
            return message
        }

        merged.append(contentsOf: allMessages.filter { !remoteIDs.contains($0.id) })
        return merged
    }

    /// Replace every text segment with one authoritative text segment,
    /// preserving the positions of tool parts relative to the first segment.
    private static func replacingText(in parts: [MessagePart], with text: String) -> MessageContent {
        let firstTextIndex = parts.firstIndex { part in
            if case .text = part { return true }
            return false
        }
        var result = parts.filter { part in
            if case .text = part { return false }
            return true
        }
        let index = min(firstTextIndex ?? result.count, result.count)
        result.insert(.text(text), at: index)

        if result.count == 1, case .text = result[0] {
            return .text(text)
        }
        return .parts(result)
    }

    private func hasRecoveredAnswer(in newMessages: [ChatMessage]) -> Bool {
        guard let assistantMessageID else {
            return newMessages.count > allMessages.count
        }
        guard let remote = newMessages.first(where: { $0.id == assistantMessageID }) else {
            return false
        }
        let localText = allMessages.first(where: { $0.id == assistantMessageID })?.visibleText ?? ""
        return !remote.visibleText.isEmpty && remote.visibleText.count > localText.count
    }

    private func appendPartialIfNeeded() {
        guard !partialAppended,
              assembler.hasContent,
              let assistantMessageID else { return }
        partialAppended = true
        allMessages.append(assembler.message(
            id: assistantMessageID,
            parentID: currentUserMessageID,
            createdAt: assistantCreatedAt
        ))
        if let parent = currentUserMessageID {
            selectedBranches[parent] = assistantMessageID
        }
        liveMessage = nil
    }

    /// Rebuild the single visible root-to-leaf path. Legacy messages with no
    /// parent are chained linearly; explicit parents preserve branches.
    private func rebuildVisiblePath() {
        guard !allMessages.isEmpty else {
            messages = []
            return
        }

        let ids = Set(allMessages.map(\.id))
        var previous: String?
        for index in allMessages.indices {
            if index == 0 {
                allMessages[index].parentID = nil
            } else if let parent = allMessages[index].parentID, ids.contains(parent) {
                // Keep an explicit, resolvable parent.
            } else {
                allMessages[index].parentID = previous
            }
            previous = allMessages[index].id
        }

        var children: [String: [ChatMessage]] = [:]
        var roots: [ChatMessage] = []
        for message in allMessages {
            if let parent = message.parentID, ids.contains(parent) {
                children[parent, default: []].append(message)
            } else {
                roots.append(message)
            }
        }

        for (parent, siblings) in children {
            if isStreaming, parent == streamingParentID { continue }
            if let selected = selectedBranches[parent],
               siblings.contains(where: { $0.id == selected }) {
                continue
            }
            selectedBranches[parent] = siblings.last?.id
        }

        var path: [ChatMessage] = []
        var cursor = roots.first
        var seen = Set<String>()
        while let message = cursor, !seen.contains(message.id) {
            seen.insert(message.id)
            path.append(message)
            if isStreaming, message.id == streamingParentID { break }
            let siblings = children[message.id] ?? []
            guard !siblings.isEmpty else { break }
            if let selected = selectedBranches[message.id],
               let match = siblings.first(where: { $0.id == selected }) {
                cursor = match
            } else {
                cursor = siblings.last
            }
        }
        messages = path
    }

    private func maybeGenerateTitle(assistantText: String) async {
        guard !didAttemptTitle,
              title == "New Chat",
              let chat = app.chat,
              let userText = firstUserText,
              !userText.isEmpty,
              savesHistory else { return }

        didAttemptTitle = true
        let fallback = TitleSanitizer.fallback(from: userText)

        do {
            let raw = try await chat.generateTitle(
                userText: userText,
                assistantText: assistantText
            )
            let cleaned = TitleSanitizer.clean(raw, fallback: fallback)
            title = cleaned
            try await chat.renameThread(id: thread.id, title: cleaned)
            await app.cache?.updateTitle(threadID: thread.id, title: cleaned)
            onThreadUpdated?(snapshot(messageCount: allMessages.count))
        } catch {
            Self.logger.error(
                "title generation failed: \(error.localizedDescription, privacy: .public)"
            )
            title = fallback
            onThreadUpdated?(snapshot(messageCount: allMessages.count))
        }
    }

    private func snapshot(messageCount: Int) -> ChatThread {
        ChatThread(
            id: thread.id,
            title: title,
            createdAt: thread.createdAt,
            updatedAt: Date(),
            messageCount: messageCount
        )
    }

    private func errorText(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
