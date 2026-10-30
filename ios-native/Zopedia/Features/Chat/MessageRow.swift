import MarkdownUI
import SwiftUI
import ZopediaKit

struct MessageRow: View {
    @Environment(AppEnvironment.self) private var app

    let message: ChatMessage
    let sessionID: String
    var isStreaming: Bool = false
    var onAnswer: ((String, String, String) -> Void)?
    var onDecision: ((String, String, Bool) -> Void)?

    @State private var showReasoning = false

    var body: some View {
        switch message.role {
        case .user:
            userBubble
        case .assistant:
            assistantBlock
        case .system, .tool:
            systemBlock
        }
    }

    private var parts: [MessagePart] {
        switch message.content {
        case .text(let text):
            return [.text(text)]
        case .parts(let parts):
            return parts
        case .object:
            return []
        }
    }

    private var timestamp: String? {
        guard message.createdAt.timeIntervalSince1970 > 0 else { return nil }
        if Calendar.current.isDateInToday(message.createdAt) {
            return message.createdAt.formatted(date: .omitted, time: .shortened)
        }
        return message.createdAt.formatted(date: .abbreviated, time: .shortened)
    }

    private var userBubble: some View {
        HStack {
            Spacer(minLength: 48)
            VStack(alignment: .trailing, spacing: 4) {
                if let name = message.localImageName, let image = localImage(named: name) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .accessibilityLabel("Attached image")
                }

                if !message.visibleText.isEmpty, !isImagePlaceholderOnly {
                    Text(message.visibleText)
                        .textSelection(.enabled)
                        .foregroundStyle(ZTheme.foreground)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(
                            ZTheme.userBubble,
                            in: UnevenRoundedRectangle(
                                topLeadingRadius: ZTheme.bubbleRadius,
                                bottomLeadingRadius: ZTheme.bubbleRadius,
                                bottomTrailingRadius: ZTheme.bubbleRadius,
                                topTrailingRadius: 4,
                                style: .continuous
                            )
                        )
                }

                if let timestamp {
                    Text(timestamp)
                        .font(.caption2)
                        .foregroundStyle(ZTheme.mutedForeground)
                }
            }
        }
    }

    private var isImagePlaceholderOnly: Bool {
        message.localImageName != nil && message.visibleText == "[image attachment]"
    }

    private func localImage(named name: String) -> UIImage? {
        let url = app.cacheRoot.appendingPathComponent("attachments/\(name)")
        return UIImage(contentsOfFile: url.path)
    }

    private var assistantBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let reasoning = message.reasoningContent, !reasoning.isEmpty {
                DisclosureGroup(isExpanded: $showReasoning) {
                    Text(reasoning)
                        .font(.callout)
                        .foregroundStyle(ZTheme.mutedForeground)
                        .textSelection(.enabled)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(ZTheme.muted, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                } label: {
                    Label(
                        isStreaming ? "Thinking…" : "Thought",
                        systemImage: "lightbulb"
                    )
                    .font(.caption)
                    .foregroundStyle(ZTheme.mutedForeground)
                }
                .onAppear {
                    if isStreaming { showReasoning = true }
                }
            }

            ForEach(Array(parts.enumerated()), id: \.offset) { _, part in
                switch part {
                case .text(let text):
                    textBlock(text)
                case .tool(let tool):
                    ToolCardView(
                        tool: tool,
                        fallbackSessionID: sessionID,
                        onAnswer: onAnswer,
                        onDecision: onDecision
                    )
                case .reasoning, .unknown:
                    EmptyView()
                }
            }

            if !isStreaming, let timestamp {
                Text(timestamp)
                    .font(.caption2)
                    .foregroundStyle(ZTheme.mutedForeground)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func textBlock(_ text: String) -> some View {
        if text.isEmpty {
            EmptyView()
        } else if isStreaming {
            // MarkdownUI re-parses the whole message on every delta, which is what
            // made streaming jitter. Plain text keeps the stream smooth; formatting
            // appears when the message completes.
            Text(text)
                .font(.body)
                .foregroundStyle(ZTheme.foreground)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Markdown(WikiLinkPreprocessor.preprocess(text))
                .markdownTheme(.zopedia)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var systemBlock: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(message.visibleText)
                .font(.caption)
                .foregroundStyle(ZTheme.mutedForeground)
                .textSelection(.enabled)

            if let timestamp {
                Text(timestamp)
                    .font(.caption2)
                    .foregroundStyle(ZTheme.mutedForeground)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
