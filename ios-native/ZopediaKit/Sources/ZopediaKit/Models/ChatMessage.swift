import Foundation

public struct ToolCallPart: Codable, Hashable, Sendable {
    public var toolCallID: String
    public var toolName: String
    public var args: JSONValue?
    public var result: String?

    public init(
        toolCallID: String,
        toolName: String,
        args: JSONValue? = nil,
        result: String? = nil
    ) {
        self.toolCallID = toolCallID
        self.toolName = toolName
        self.args = args
        self.result = result
    }
}

public enum MessagePart: Hashable, Sendable {
    case text(String)
    case reasoning(String)
    case tool(ToolCallPart)
    case unknown(kind: String, payload: JSONValue)
}

extension MessagePart: Codable {
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: AnyCodingKey.self)
        let type = try container.decodeIfPresent(String.self, forKey: AnyCodingKey("type")) ?? "text"

        switch type {
        case "text":
            self = .text(try container.decodeIfPresent(String.self, forKey: AnyCodingKey("text")) ?? "")
        case "reasoning", "thinking":
            let text = try container.decodeIfPresent(String.self, forKey: AnyCodingKey("text"))
                ?? container.decodeIfPresent(String.self, forKey: AnyCodingKey("reasoning"))
                ?? container.decodeIfPresent(String.self, forKey: AnyCodingKey("reasoning_content"))
                ?? ""
            self = .reasoning(text)
        case "tool-call", "tool_call":
            let callID = try container.decodeIfPresent(String.self, forKey: AnyCodingKey("toolCallId"))
                ?? container.decodeIfPresent(String.self, forKey: AnyCodingKey("tool_call_id"))
                ?? ""
            let name = try container.decodeIfPresent(String.self, forKey: AnyCodingKey("toolName"))
                ?? container.decodeIfPresent(String.self, forKey: AnyCodingKey("tool_name"))
                ?? ""
            let args = try container.decodeIfPresent(JSONValue.self, forKey: AnyCodingKey("args"))
            let result = try container.decodeIfPresent(String.self, forKey: AnyCodingKey("result"))
            self = .tool(ToolCallPart(
                toolCallID: callID, toolName: name, args: args, result: result
            ))
        default:
            let payload = try container.decodeIfPresent(JSONValue.self, forKey: AnyCodingKey("payload"))
            self = .unknown(kind: type, payload: payload ?? .null)
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: AnyCodingKey.self)
        switch self {
        case .text(let text):
            try container.encode("text", forKey: AnyCodingKey("type"))
            try container.encode(text, forKey: AnyCodingKey("text"))
        case .reasoning(let text):
            try container.encode("reasoning", forKey: AnyCodingKey("type"))
            try container.encode(text, forKey: AnyCodingKey("text"))
        case .tool(let tool):
            try container.encode("tool-call", forKey: AnyCodingKey("type"))
            try container.encode(tool.toolCallID, forKey: AnyCodingKey("toolCallId"))
            try container.encode(tool.toolName, forKey: AnyCodingKey("toolName"))
            try container.encodeIfPresent(tool.args, forKey: AnyCodingKey("args"))
            try container.encodeIfPresent(tool.result, forKey: AnyCodingKey("result"))
        case .unknown(let kind, let payload):
            try container.encode(kind, forKey: AnyCodingKey("type"))
            try container.encode(payload, forKey: AnyCodingKey("payload"))
        }
    }
}

public enum MessageContent: Hashable, Sendable {
    case text(String)
    case parts([MessagePart])
    case object(JSONValue)
}

extension MessageContent: Codable {
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .text("")
            return
        }

        if let string = try? container.decode(String.self) {
            // The server serializes list content with json.dumps, so a string
            // that parses as an array is really a parts payload.
            if let data = string.data(using: .utf8),
               let raw = try? JSONSerialization.jsonObject(with: data) {
                if let array = raw as? [Any],
                   let arrayData = try? JSONSerialization.data(withJSONObject: array) {
                    self = .parts(try JSONDecoder().decode([MessagePart].self, from: arrayData))
                    return
                }
                if let object = raw as? [String: Any] {
                    self = .object(try JSONValue(any: object))
                    return
                }
            }
            self = .text(string)
            return
        }

        if let parts = try? container.decode([MessagePart].self) {
            self = .parts(parts)
            return
        }

        self = .object(try container.decode(JSONValue.self))
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .text(let text):
            try container.encode(text)
        case .parts(let parts):
            try container.encode(parts)
        case .object(let value):
            try container.encode(value)
        }
    }
}

public struct ChatMessage: Identifiable, Codable, Hashable, Sendable {
    public enum Role: String, Codable, Hashable, Sendable {
        case user
        case assistant
        case system
        case tool
    }

    public let id: String
    public var role: Role
    public var content: MessageContent
    public var reasoningContent: String?
    public var parentID: String?
    public var createdAt: Date
    /// Local-only cache filename for an attached image. Never sent to the server.
    public var localImageName: String?

    public init(
        id: String,
        role: Role,
        content: MessageContent,
        reasoningContent: String? = nil,
        parentID: String? = nil,
        createdAt: Date = Date(),
        localImageName: String? = nil
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.reasoningContent = reasoningContent
        self.parentID = parentID
        self.createdAt = createdAt
        self.localImageName = localImageName
    }

    enum CodingKeys: String, CodingKey {
        case id
        case role
        case content
        case reasoningContent = "reasoning_content"
        case parentID = "parent_id"
        case createdAt = "created_at"
        case localImageName
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        role = try container.decodeIfPresent(Role.self, forKey: .role) ?? .assistant
        content = try container.decodeIfPresent(MessageContent.self, forKey: .content) ?? .text("")
        reasoningContent = try container.decodeIfPresent(String.self, forKey: .reasoningContent)
        parentID = try container.decodeIfPresent(String.self, forKey: .parentID)
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
            ?? Date(timeIntervalSince1970: 0)
        localImageName = try container.decodeIfPresent(String.self, forKey: .localImageName)
    }

    /// Visible text across the supported content shapes.
    public var visibleText: String {
        switch content {
        case .text(let text):
            return text
        case .parts(let parts):
            return parts.compactMap { part in
                if case .text(let text) = part { return text }
                return nil
            }.joined()
        case .object:
            return ""
        }
    }

    /// Split legacy inline `<think>…</think>` blocks into reasoning.
    public func normalized() -> ChatMessage {
        guard reasoningContent == nil,
              case .text(let text) = content,
              text.contains("<think>") else {
            return self
        }

        var visible = text
        var reasoning = ""
        while let start = visible.range(of: "<think>"),
              let end = visible.range(of: "</think>", range: start.upperBound..<visible.endIndex) {
            reasoning += String(visible[start.upperBound..<end.lowerBound])
            visible.removeSubrange(start.lowerBound..<end.upperBound)
        }

        var message = self
        message.content = .text(visible.trimmingCharacters(in: .whitespacesAndNewlines))
        message.reasoningContent = reasoning.isEmpty ? nil : reasoning
        return message
    }
}

/// Payload sent when persisting messages to the server.
public struct MessagePayload: Encodable, Sendable {
    public let id: String
    public let role: String
    public let content: MessageContent
    public let reasoningContent: String?
    public let parentID: String?
    public let createdAt: String?

    public init(message: ChatMessage) {
        id = message.id
        role = message.role.rawValue
        content = message.content
        reasoningContent = message.reasoningContent
        parentID = message.parentID
        createdAt = ZopediaDate.string(from: message.createdAt)
    }

    enum CodingKeys: String, CodingKey {
        case id
        case role
        case content
        case reasoningContent = "reasoning_content"
        case parentID = "parent_id"
        case createdAt = "created_at"
    }
}
