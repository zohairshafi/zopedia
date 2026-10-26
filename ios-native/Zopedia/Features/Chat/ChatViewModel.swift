import Foundation
import Observation
import os
import ZopediaKit

@MainActor
@Observable
final class ChatViewModel {
    private static let logger = Logger(subsystem: "com.zopedia.client", category: "chat")

    let thread: ChatThread

    private(set) var messages: [ChatMessage] = []
    private(set) var liveMessage: ChatMessage?
    private(set) var toolStatus: String?
    private(set) var isStreaming = false
    private(set) var isLoading = true
    private(set) var errorMessage: String?
    private(set) var title: String
    private(set) var needsRecovery = false

    var draft = ""

    var canSend: Bool {
        !isStreaming && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private let app: AppEnvironment
    private var isNewThread: Bool
    private var assembler = ChatStreamAssembler()
    private var streamTask: Task<Void, Never>?
    private var lastPublish = Date.distantPast
    private var firstUserText: String?
    private var currentUserMessageID: String?
    private var assistantMessageID: String?
    private var assistantCreatedAt = Date()
    private var partialAppended = false
    private var isBackgroundSuspended = false
    private var didAttemptTitle = false
    private var didSaveThread = false
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
            messages = cached.messages.map { $0.normalized() }
            title = cached.thread.title
        }

        isLoading = messages.isEmpty
        defer { isLoading = false }

        guard !isNewThread, let chat = app.chat else { return }

        do {
            let response = try await chat.getThread(thread.id)
            messages = mergeServerMessages(response.messages)
            title = response.thread.title
            await app.cache?.saveThread(response.thread, messages: messages)
            errorMessage = nil
        } catch let error as APIError {
            if case .http(let status, _) = error, status == 404 {
                messages = []
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

        let now = Date()
        let userMessage = ChatMessage(
            id: UUID().uuidString,
            role: .user,
            content: .text(contentText),
            createdAt: now,
            localImageName: localImageName
        )
        messages.append(userMessage)
        currentUserMessageID = userMessage.id
        if firstUserText == nil {
            firstUserText = typed.isEmpty ? (attachmentName ?? "Attachment") : typed
        }

        if app.permissions?.canSaveChatHistory ?? true {
            do {
                _ = try await chat.appendMessages(
                    threadID: thread.id,
                    title: isNewThread ? title : nil,
                    messages: [userMessage]
                )
                if isNewThread {
                    isNewThread = false
                    didSaveThread = true
                    onThreadUpdated?(snapshot(messageCount: messages.count))
                }
            } catch {
                errorMessage = "Could not save your message: \(errorText(error))"
            }
        }

        startStreaming(
            client: client,
            text: contentText,
            parentID: userMessage.id,
            imageBase64: imageBase64
        )
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
        text: String,
        parentID: String,
        imageBase64: String?
    ) {
        let assistantID = UUID().uuidString
        assistantMessageID = assistantID
        assistantCreatedAt = Date()
        assembler = ChatStreamAssembler()
        partialAppended = false
        toolStatus = nil
        errorMessage = nil
        isStreaming = true
        publish(force: true)

        let outgoing = messages.map {
            OutgoingMessage(role: $0.role.rawValue, content: $0.visibleText)
        }
        let request = ChatRequest(
            messages: outgoing,
            sessionID: thread.id,
            assistantMessageID: assistantID,
            parentID: parentID,
            imageBase64: imageBase64
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
            toolStatus = status
        case .error(let message):
            errorMessage = message
        default:
            break
        }
        publish(force: false)
    }

    private func publish(force: Bool) {
        guard let assistantMessageID, isStreaming else { return }
        let now = Date()
        if !force && now.timeIntervalSince(lastPublish) < 0.05 { return }
        lastPublish = now
        liveMessage = assembler.message(
            id: assistantMessageID,
            parentID: currentUserMessageID,
            createdAt: assistantCreatedAt
        )
    }

    private func finish() async {
        streamTask = nil
        isStreaming = false
        toolStatus = nil

        guard assembler.hasContent, let assistantMessageID else {
            liveMessage = nil
            errorMessage = "The model returned an empty response."
            return
        }

        let final = assembler.message(
            id: assistantMessageID,
            parentID: currentUserMessageID,
            createdAt: assistantCreatedAt
        )
        messages.append(final)
        liveMessage = nil

        if app.permissions?.canSaveChatHistory ?? true, let chat = app.chat {
            do {
                _ = try await chat.appendMessages(
                    threadID: thread.id,
                    title: nil,
                    messages: [final]
                )
                let updated = snapshot(messageCount: messages.count)
                await app.cache?.saveThread(updated, messages: messages)
                onThreadUpdated?(updated)
            } catch {
                errorMessage = "Answer received, but it could not be saved: \(errorText(error))"
            }
        }

        await maybeGenerateTitle(assistantText: final.visibleText)
    }

    private func stopCleanly() {
        streamTask = nil
        isStreaming = false
        toolStatus = nil
        appendPartialIfNeeded()

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
        isStreaming = false
        toolStatus = nil
        appendPartialIfNeeded()

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

                messages = merged
                title = response.thread.title
                await app.cache?.saveThread(response.thread, messages: merged)

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
            messages = mergeServerMessages(response.messages)
            title = response.thread.title
            await app.cache?.saveThread(response.thread, messages: messages)
        } catch {
            // Offline or transient failure: keep the cached view.
        }
    }

    /// Merge server messages with local-only metadata (image names) and with
    /// tool cards the server's fallback persistence drops.
    private func mergeServerMessages(_ serverMessages: [ChatMessage]) -> [ChatMessage] {
        var localByID: [String: ChatMessage] = [:]
        for message in messages {
            localByID[message.id] = message
        }

        return serverMessages.map { remote in
            var merged = remote.normalized()
            guard let local = localByID[merged.id] else { return merged }

            if merged.localImageName == nil {
                merged.localImageName = local.localImageName
            }
            if merged.reasoningContent == nil {
                merged.reasoningContent = local.reasoningContent
            }

            if case .parts(let localParts) = local.content, case .text = merged.content {
                var parts: [MessagePart] = localParts.filter {
                    if case .tool = $0 { return true }
                    return false
                }
                if !merged.visibleText.isEmpty {
                    parts.append(.text(merged.visibleText))
                }
                if !parts.isEmpty {
                    merged.content = .parts(parts)
                }
            }
            return merged
        }
    }

    private func hasRecoveredAnswer(in newMessages: [ChatMessage]) -> Bool {
        guard let assistantMessageID else {
            return newMessages.count > messages.count
        }
        guard let remote = newMessages.first(where: { $0.id == assistantMessageID }) else {
            return false
        }
        let localText = messages.first(where: { $0.id == assistantMessageID })?.visibleText ?? ""
        return !remote.visibleText.isEmpty && remote.visibleText.count > localText.count
    }

    private func appendPartialIfNeeded() {
        guard !partialAppended,
              assembler.hasContent,
              let assistantMessageID else { return }
        partialAppended = true
        messages.append(assembler.message(
            id: assistantMessageID,
            parentID: currentUserMessageID,
            createdAt: assistantCreatedAt
        ))
        liveMessage = nil
    }

    private func maybeGenerateTitle(assistantText: String) async {
        guard !didAttemptTitle,
              title == "New Chat",
              let chat = app.chat,
              let userText = firstUserText,
              !userText.isEmpty,
              app.permissions?.canSaveChatHistory ?? true else { return }

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
            onThreadUpdated?(snapshot(messageCount: messages.count))
        } catch {
            Self.logger.error(
                "title generation failed: \(error.localizedDescription, privacy: .public)"
            )
            title = fallback
            onThreadUpdated?(snapshot(messageCount: messages.count))
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
