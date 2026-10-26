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

    private var toolParts: [ToolCallPart] {
        guard case .parts(let parts) = message.content else { return [] }
        return parts.compactMap { part in
            if case .tool(let tool) = part { return tool }
            return nil
        }
    }

    private var userBubble: some View {
        HStack {
            Spacer(minLength: 48)
            VStack(alignment: .trailing, spacing: 6) {
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
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(
                            Color.accentColor.opacity(0.14),
                            in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                        )
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
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .padding(.top, 6)
                } label: {
                    Label(
                        isStreaming ? "Thinking…" : "Reasoning",
                        systemImage: "brain"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                .onAppear {
                    if isStreaming { showReasoning = true }
                }
            }

            ForEach(toolParts, id: \.toolCallID) { tool in
                ToolCardView(
                    tool: tool,
                    fallbackSessionID: sessionID,
                    onAnswer: onAnswer,
                    onDecision: onDecision
                )
            }

            if !message.visibleText.isEmpty {
                Markdown(message.visibleText)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var systemBlock: some View {
        Text(message.visibleText)
            .font(.caption)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
