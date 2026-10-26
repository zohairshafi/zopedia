import Foundation

/// Accumulates a live chat stream into a message the UI can render and persist.
public struct ChatStreamAssembler: Sendable {
    public private(set) var text = ""
    public private(set) var reasoning = ""
    public private(set) var tools: [ToolCallPart] = []
    public private(set) var usage: JSONValue?
    public private(set) var errorMessage: String?
    public private(set) var isDone = false
    public private(set) var lastToolStatus: String?

    public init() {}

    public mutating func apply(_ event: ChatStreamEvent) {
        switch event {
        case .textDelta(let delta):
            text += delta
        case .reasoningDelta(let delta):
            reasoning += delta
        case .toolStart(let start):
            tools.append(
                ToolCallPart(
                    toolCallID: start.callID,
                    toolName: start.name,
                    args: start.arguments
                )
            )
        case .toolEnd(let end):
            if let position = tools.firstIndex(where: { $0.toolCallID == end.callID }) {
                tools[position].result = end.result
            } else {
                tools.append(
                    ToolCallPart(
                        toolCallID: end.callID,
                        toolName: end.name,
                        result: end.result
                    )
                )
            }
        case .toolStatus(let status):
            lastToolStatus = status
        case .usage(let value):
            usage = value
        case .error(let message):
            errorMessage = message
        case .done:
            isDone = true
        }
    }

    public var hasContent: Bool {
        !text.isEmpty || !reasoning.isEmpty || !tools.isEmpty
    }

    /// Build the message that gets rendered and, on success, persisted.
    public func message(
        id: String,
        parentID: String?,
        createdAt: Date
    ) -> ChatMessage {
        var parts: [MessagePart] = []
        if !reasoning.isEmpty {
            parts.append(.reasoning(reasoning))
        }
        parts.append(contentsOf: tools.map { .tool($0) })
        if !text.isEmpty {
            parts.append(.text(text))
        }

        let content: MessageContent
        if parts.count == 1, case .text = parts[0] {
            content = .text(text)
        } else if parts.isEmpty {
            content = .text("")
        } else {
            content = .parts(parts)
        }

        return ChatMessage(
            id: id,
            role: .assistant,
            content: content,
            reasoningContent: reasoning.isEmpty ? nil : reasoning,
            parentID: parentID,
            createdAt: createdAt
        )
    }
}
