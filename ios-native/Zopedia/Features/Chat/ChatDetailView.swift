import Combine
import SwiftUI
import ZopediaKit

struct ChatDetailView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let thread: ChatThread
    let isNew: Bool
    let onThreadUpdated: ((ChatThread) -> Void)?

    @State private var model: ChatViewModel?
    @State private var isFollowing = true
    @State private var viewportHeight: CGFloat = 0
    @State private var showJumpToMessage = false
    @State private var exportFile: ExportFile?
    @State private var exportError: String?

    init(
        thread: ChatThread,
        isNew: Bool = false,
        onThreadUpdated: ((ChatThread) -> Void)? = nil
    ) {
        self.thread = thread
        self.isNew = isNew
        self.onThreadUpdated = onThreadUpdated
    }

    var body: some View {
        Group {
            if let model {
                content(model)
            } else {
                ProgressView()
            }
        }
        .background(ZTheme.background)
        .navigationTitle(model?.title ?? thread.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(ZTheme.background, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .task {
            guard model == nil else { return }
            let created = ChatViewModel(
                thread: thread,
                app: app,
                isNew: isNew,
                onThreadUpdated: onThreadUpdated
            )
            model = created
            await created.load()
        }
        .onChange(of: scenePhase) { _, phase in
            guard let model else { return }
            switch phase {
            case .background:
                model.prepareForBackground()
            case .active:
                Task { await model.recover() }
            default:
                break
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Menu {
                    if let model {
                        Button {
                            Task { await model.setLogging(!model.isLogging) }
                        } label: {
                            Label(
                                model.isLogging ? "Stop Logging Chat to Wiki" : "Log Chat to Wiki",
                                systemImage: model.isLogging
                                    ? "checkmark.circle.fill"
                                    : "circle"
                            )
                        }
                        .disabled(
                            model.isStreaming
                                || app.permissions?.canSaveChatHistory == false
                        )

                        Divider()
                    }

                    Button {
                        exportHTML()
                    } label: {
                        Label("Export as HTML", systemImage: "square.and.arrow.up")
                    }
                    .disabled(model?.messages.isEmpty ?? true)

                    Button {
                        showJumpToMessage = true
                    } label: {
                        Label("Jump to message", systemImage: "list.bullet")
                    }
                    .disabled(model?.userMessages.isEmpty ?? true)
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .accessibilityLabel("Chat actions")
            }
        }
        .sheet(item: $exportFile) { file in
            ShareSheet(items: [file.url])
                .presentationDetents([.medium, .large])
        }
        .alert("Could not export chat", isPresented: exportErrorBinding) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(exportError ?? "")
        }
    }

    private var exportErrorBinding: Binding<Bool> {
        Binding(
            get: { exportError != nil },
            set: { if !$0 { exportError = nil } }
        )
    }

    private func exportHTML() {
        guard let model, !model.messages.isEmpty else { return }

        let html = ChatHTMLExporter.html(
            title: model.title,
            messages: model.messages,
            serverURL: app.serverURL
        )

        let slug = model.title
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .joined(separator: "-")
        let trimmed = String(slug.prefix(60))
        let name = trimmed.isEmpty ? "Zopedia-chat" : "Zopedia-\(trimmed)"
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(name).html")

        do {
            try html.write(to: url, atomically: true, encoding: .utf8)
            exportFile = ExportFile(url: url)
        } catch {
            exportError = error.localizedDescription
        }
    }

    @ViewBuilder
    private func content(_ model: ChatViewModel) -> some View {
        VStack(spacing: 0) {
            if let error = model.errorMessage {
                Text(error)
                    .font(.callout)
                    .foregroundStyle(ZTheme.destructive)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(ZTheme.destructive.opacity(0.08))
            }

            messageList(model)

            if model.isStreaming,
               let status = model.toolStatus,
               !status.isEmpty,
               let since = model.toolStatusSince {
                ToolStatusPill(status: status, since: since)
                    .padding(.bottom, 4)
            }

            ComposerView(model: model)
        }
        .background(ZTheme.background)
    }

    @ViewBuilder
    private func branchBar(for message: ChatMessage, model: ChatViewModel) -> some View {
        let info = model.branchInfo(for: message)
        let isLast = model.lastVisibleAssistantID == message.id

        if info != nil || isLast {
            HStack(spacing: 4) {
                if let info {
                    branchButton("chevron.left", disabled: model.isStreaming) {
                        model.selectSibling(of: message, offset: -1)
                    }
                    Text("\(info.index + 1) / \(info.count)")
                        .font(.caption2)
                        .monospacedDigit()
                        .foregroundStyle(ZTheme.mutedForeground)
                    branchButton("chevron.right", disabled: model.isStreaming) {
                        model.selectSibling(of: message, offset: 1)
                    }
                }

                if isLast {
                    Button {
                        isFollowing = true
                        Task { await model.regenerate(assistantMessageID: message.id) }
                    } label: {
                        Label("Regenerate", systemImage: "arrow.clockwise")
                            .font(.caption)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 8)
                            .frame(minHeight: 36)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(ZTheme.mutedForeground)
                    .disabled(model.isStreaming)
                }

                Spacer(minLength: 0)
            }
            .padding(.leading, 2)
        }
    }

    private func branchButton(
        _ icon: String,
        disabled: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.caption.weight(.semibold))
                .frame(width: 40, height: 40)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(ZTheme.mutedForeground)
        .disabled(disabled)
    }

    private func messageList(_ model: ChatViewModel) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(model.displayMessages) { message in
                        VStack(alignment: .leading, spacing: 4) {
                            MessageRow(
                                message: message,
                                sessionID: thread.id,
                                isStreaming: message.id == model.liveMessage?.id,
                                onAnswer: { session, callID, answer in
                                    Task {
                                        await model.answerQuestion(
                                            sessionID: session,
                                            toolCallID: callID,
                                            answer: answer
                                        )
                                    }
                                },
                                onDecision: { session, callID, approve in
                                    Task {
                                        await model.decideApproval(
                                            sessionID: session,
                                            toolCallID: callID,
                                            approve: approve
                                        )
                                    }
                                }
                            )

                            if message.role == .assistant,
                               message.id != model.liveMessage?.id {
                                branchBar(for: message, model: model)
                            }
                        }
                        .id(message.id)
                    }

                    Color.clear
                        .frame(height: 1)
                        .id("bottom")
                        .background(
                            GeometryReader { geometry in
                                Color.clear.preference(
                                    key: BottomEdgeKey.self,
                                    value: geometry.frame(in: .named("chatScroll")).maxY
                                )
                            }
                        )
                }
                .padding()
                .frame(maxWidth: 820)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .onReceive(NotificationCenter.default.publisher(for: .chatScrollToBottom)) { _ in
                isFollowing = true
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo("bottom", anchor: .bottom)
                }
            }
            .coordinateSpace(name: "chatScroll")
            .background(
                GeometryReader { geometry in
                    Color.clear.preference(
                        key: ViewportHeightKey.self,
                        value: geometry.size.height
                    )
                }
            )
            .simultaneousGesture(
                DragGesture(minimumDistance: 1).onChanged { value in
                    if value.translation.height > 20 {
                        isFollowing = false
                    }
                }
            )
            .overlay {
                if model.isLoading && model.displayMessages.isEmpty {
                    ProgressView()
                } else if model.displayMessages.isEmpty,
                          model.errorMessage == nil {
                    if isNew {
                        VStack(spacing: 14) {
                            ZopediaLogo(size: 112)
                            Text("Zopedia")
                                .font(.title2.weight(.semibold))
                                .foregroundStyle(ZTheme.foreground)
                            Text("Chat with your personal knowledge base.")
                                .font(.callout)
                                .foregroundStyle(ZTheme.mutedForeground)
                        }
                        .multilineTextAlignment(.center)
                        .padding()
                    } else {
                        ContentUnavailableView(
                            "No messages",
                            systemImage: "bubble.left.and.text.bubble.right",
                            description: Text("This thread has no stored messages.")
                        )
                    }
                }
            }
            .overlay(alignment: .bottomTrailing) {
                if !isFollowing, !model.userMessages.isEmpty {
                    jumpToMessageButton
                }
            }
            .sheet(isPresented: $showJumpToMessage) {
                JumpToMessageSheet(
                    messages: model.userMessages,
                    onSelect: { id in
                        showJumpToMessage = false
                        isFollowing = false
                        Task { @MainActor in
                            try? await Task.sleep(nanoseconds: 250_000_000)
                            withAnimation(.easeOut(duration: 0.2)) {
                                proxy.scrollTo(id, anchor: .top)
                            }
                        }
                    },
                    onLatest: {
                        showJumpToMessage = false
                        isFollowing = true
                        withAnimation(.easeOut(duration: 0.2)) {
                            proxy.scrollTo("bottom", anchor: .bottom)
                        }
                    }
                )
            }
            .refreshable { await model.load() }
            .onPreferenceChange(ViewportHeightKey.self) { height in
                viewportHeight = height
            }
            .onPreferenceChange(BottomEdgeKey.self) { bottom in
                // Only track whether we are near the bottom. Growth during a
                // stream is handled by liveRevision; forcing a scroll here
                // also undid the system's status-bar scroll-to-top gesture.
                if bottom - viewportHeight <= 40 {
                    isFollowing = true
                }
            }
            .onChange(of: model.liveRevision) { _, _ in
                guard isFollowing else { return }
                proxy.scrollTo("bottom", anchor: .bottom)
            }
            .onChange(of: model.displayMessages.count) { _, _ in
                guard isFollowing else { return }
                if reduceMotion {
                    proxy.scrollTo("bottom", anchor: .bottom)
                } else {
                    withAnimation(.easeOut(duration: 0.15)) {
                        proxy.scrollTo("bottom", anchor: .bottom)
                    }
                }
            }
            .onChange(of: model.isStreaming) { _, streaming in
                guard !streaming, isFollowing else { return }
                // The final render switches the message to MarkdownUI and lays
                // out tables after the stream ends. Give it a beat, then pin the
                // true bottom so the last table rows and links stay visible.
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 300_000_000)
                    proxy.scrollTo("bottom", anchor: .bottom)
                }
            }
        }
    }

    private var jumpToMessageButton: some View {
        Button {
            showJumpToMessage = true
        } label: {
            Label("Jump to message", systemImage: "list.bullet")
                .font(.caption.weight(.medium))
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(ZTheme.card, in: Capsule())
                .overlay {
                    Capsule().stroke(ZTheme.border, lineWidth: 1)
                }
                .foregroundStyle(ZTheme.foreground)
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .padding(16)
        .accessibilityLabel("Jump to a message")
    }
}

private struct ExportFile: Identifiable {
    let id = UUID()
    let url: URL
}

private struct JumpToMessageSheet: View {
    let messages: [ChatMessage]
    let onSelect: (String) -> Void
    let onLatest: () -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button {
                        onLatest()
                        dismiss()
                    } label: {
                        Label("Jump to the latest message", systemImage: "arrow.down")
                            .foregroundStyle(ZTheme.primary)
                            .frame(minHeight: 44)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                }

                Section("Your messages") {
                    if messages.isEmpty {
                        Text("No messages yet.")
                            .font(.callout)
                            .foregroundStyle(ZTheme.mutedForeground)
                    } else {
                        ForEach(Array(messages.reversed())) { message in
                            Button {
                                onSelect(message.id)
                                dismiss()
                            } label: {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(preview(message))
                                        .font(.callout)
                                        .foregroundStyle(ZTheme.foreground)
                                        .lineLimit(2)
                                        .multilineTextAlignment(.leading)
                                    Text(timestamp(message.createdAt))
                                        .font(.caption2)
                                        .foregroundStyle(ZTheme.mutedForeground)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.vertical, 6)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .listRowBackground(ZTheme.background)
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle("Jump to message")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func preview(_ message: ChatMessage) -> String {
        let text = message.visibleText.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || text == "[image attachment]" {
            return "Image attachment"
        }
        return text.replacingOccurrences(of: "\n", with: " ")
    }

    private func timestamp(_ date: Date) -> String {
        guard date.timeIntervalSince1970 > 0 else { return "" }
        if Calendar.current.isDateInToday(date) {
            return date.formatted(date: .omitted, time: .shortened)
        }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

private struct BottomEdgeKey: PreferenceKey {
    static let defaultValue: CGFloat = .greatestFiniteMagnitude
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct ViewportHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}
