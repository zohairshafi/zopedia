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

    private func messageList(_ model: ChatViewModel) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(model.displayMessages) { message in
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
                    ContentUnavailableView(
                        isNew ? "Start the conversation" : "No messages",
                        systemImage: "bubble.left.and.text.bubble.right",
                        description: Text(isNew
                            ? "Send a message below."
                            : "This thread has no stored messages.")
                    )
                }
            }
            .overlay(alignment: .bottomTrailing) {
                if !isFollowing, !model.displayMessages.isEmpty {
                    jumpToLatest(proxy)
                }
            }
            .refreshable { await model.load() }
            .onPreferenceChange(ViewportHeightKey.self) { height in
                viewportHeight = height
            }
            .onPreferenceChange(BottomEdgeKey.self) { bottom in
                let distance = bottom - viewportHeight
                if distance <= 40 {
                    isFollowing = true
                } else if isFollowing {
                    // The content grew (streamed text, a table, a tool card).
                    // Keep the sentinel in view; user drags turn following off.
                    proxy.scrollTo("bottom", anchor: .bottom)
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

    private func jumpToLatest(_ proxy: ScrollViewProxy) -> some View {
        Button {
            isFollowing = true
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo("bottom", anchor: .bottom)
            }
        } label: {
            Label("Jump to latest", systemImage: "arrow.down")
                .font(.caption.weight(.medium))
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(ZTheme.card, in: Capsule())
                .overlay {
                    Capsule().stroke(ZTheme.border, lineWidth: 1)
                }
                .foregroundStyle(ZTheme.foreground)
        }
        .padding(16)
        .accessibilityLabel("Jump to the latest message")
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
