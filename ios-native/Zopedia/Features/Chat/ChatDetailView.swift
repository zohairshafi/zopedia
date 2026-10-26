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
        .navigationTitle(model?.title ?? thread.title)
        .navigationBarTitleDisplayMode(.inline)
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
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(.red.opacity(0.08))
            }

            messageList(model)
            ComposerView(model: model)
        }
    }

    private func messageList(_ model: ChatViewModel) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(model.messages) { message in
                        MessageRow(
                            message: message,
                            sessionID: thread.id,
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
                    }

                    if let live = model.liveMessage {
                        MessageRow(
                            message: live,
                            sessionID: thread.id,
                            isStreaming: true,
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
                    }

                    Color.clear
                        .frame(height: 1)
                        .id("bottom")
                }
                .padding()
            }
            .overlay {
                if model.isLoading && model.messages.isEmpty {
                    ProgressView()
                } else if model.messages.isEmpty,
                          model.liveMessage == nil,
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
            .refreshable { await model.load() }
            .onChange(of: model.messages.count) { _, _ in
                scrollToBottom(proxy)
            }
            .onChange(of: model.liveMessage) { _, _ in
                scrollToBottom(proxy)
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if reduceMotion {
            proxy.scrollTo("bottom", anchor: .bottom)
        } else {
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo("bottom", anchor: .bottom)
            }
        }
    }
}
