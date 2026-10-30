import Foundation

/// Accumulates a live chat stream into a message the UI can render and persist.
///
/// Text and tool calls are kept in arrival order so a tool call that happens
/// mid-answer stays where it occurred instead of being hoisted above the text.
public struct ChatStreamAssembler: Sendable {
    public private(set) var parts: [MessagePart] = []
    public private(set) var reasoning = ""
    public private(set) var usage: JSONValue?
    public private(set) var errorMessage: String?
    public private(set) var isDone = false
    public private(set) var lastToolStatus: String?

    public init() {}

    /// All text across the stream, in order.
    public var text: String {
        parts.compactMap { part in
            if case .text(let text) = part { return text }
            return nil
        }.joined()
    }

    public var tools: [ToolCallPart] {
        parts.compactMap { part in
            if case .tool(let tool) = part { return tool }
            return nil
        }
    }

    public mutating func apply(_ event: ChatStreamEvent) {
        switch event {
        case .textDelta(let delta):
            appendText(delta)
        case .reasoningDelta(let delta):
            reasoning += delta
        case .toolStart(let start):
            parts.append(.tool(ToolCallPart(
                toolCallID: start.callID,
                toolName: start.name,
                args: start.arguments
            )))
        case .toolEnd(let end):
            updateTool(end)
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
        !parts.isEmpty || !reasoning.isEmpty
    }

    /// Build the message that gets rendered and, on success, persisted.
    public func message(
        id: String,
        parentID: String?,
        createdAt: Date
    ) -> ChatMessage {
        let content: MessageContent
        if parts.isEmpty {
            content = .text("")
        } else if parts.count == 1, case .text = parts[0] {
            content = .text(text)
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

    private mutating func appendText(_ delta: String) {
        if case .text(let existing) = parts.last {
            parts[parts.count - 1] = .text(existing + delta)
        } else {
            parts.append(.text(delta))
        }
    }

    private mutating func updateTool(_ end: ToolEnd) {
        if let position = parts.firstIndex(where: { part in
            if case .tool(let tool) = part { return tool.toolCallID == end.callID }
            return false
        }) {
            if case .tool(var tool) = parts[position] {
                tool.result = end.result
                parts[position] = .tool(tool)
            }
            return
        }

        parts.append(.tool(ToolCallPart(
            toolCallID: end.callID,
            toolName: end.name,
            result: end.result
        )))
    }
}
