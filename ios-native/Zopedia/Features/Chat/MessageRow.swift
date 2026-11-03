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
        if message.subtype == "compact" {
            compactBlock
        } else {
            switch message.role {
            case .user:
                userBubble
            case .assistant:
                assistantBlock
            case .system, .tool:
                systemBlock
            }
        }
    }

    private var hasReasoningParts: Bool {
        parts.contains { part in
            if case .reasoning = part { return true }
            return false
        }
    }

    private var compactBlock: some View {
        DisclosureGroup {
            Text(message.visibleText)
                .font(.callout)
                .foregroundStyle(ZTheme.mutedForeground)
                .textSelection(.enabled)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(ZTheme.muted, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        } label: {
            Label("Conversation compacted", systemImage: "rectangle.compress.vertical")
                .font(.caption)
                .foregroundStyle(ZTheme.mutedForeground)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
            // Older/server-provided messages carry reasoning outside the parts
            // list. Render that once above the answer; streamed messages carry
            // reasoning parts so it stays in order with tool calls.
            if !hasReasoningParts,
               let reasoning = message.reasoningContent,
               !reasoning.isEmpty {
                reasoningBlock(reasoning)
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
                case .reasoning(let text):
                    reasoningBlock(text)
                case .unknown:
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

    private func reasoningBlock(_ reasoning: String) -> some View {
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
            // Do not enable text selection here: SwiftUI ignores the openURL
            // action for links inside selectable Text, which breaks wiki links.
            ZMarkdown(text: text)
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
