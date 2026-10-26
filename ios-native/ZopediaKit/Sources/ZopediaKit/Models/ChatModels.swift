import Foundation

public struct ToolStart: Equatable, Sendable {
    public let name: String
    public let callID: String
    public let arguments: JSONValue

    public init(name: String, callID: String, arguments: JSONValue) {
        self.name = name
        self.callID = callID
        self.arguments = arguments
    }
}

public struct ToolEnd: Equatable, Sendable {
    public let name: String
    public let callID: String
    public let result: String

    public init(name: String, callID: String, result: String) {
        self.name = name
        self.callID = callID
        self.result = result
    }
}

public enum ChatStreamEvent: Equatable, Sendable {
    case toolStatus(String)
    case toolStart(ToolStart)
    case toolEnd(ToolEnd)
    case textDelta(String)
    case reasoningDelta(String)
    case usage(JSONValue)
    case error(String)
    case done
}

public struct OutgoingMessage: Encodable, Sendable {
    public var role: String
    public var content: String

    public init(role: String, content: String) {
        self.role = role
        self.content = content
    }
}

public struct ChatRequest: Encodable, Sendable {
    public var messages: [OutgoingMessage]
    public var stream: Bool = true
    public var enableTools: Bool = true
    public var enabledTools: [String]
    public var sessionID: String?
    public var assistantMessageID: String?
    public var parentID: String?
    public var imageBase64: String?
    public var reasoningEffort: String?
    public var enableThinking: Bool?
    public var maxTokens: Int?

    public init(
        messages: [OutgoingMessage],
        enabledTools: [String] = [
            "read_wiki_page", "search_wiki", "ask_user_question", "web_search",
        ],
        sessionID: String? = nil,
        assistantMessageID: String? = nil,
        parentID: String? = nil,
        imageBase64: String? = nil,
        reasoningEffort: String? = nil,
        enableThinking: Bool? = nil,
        maxTokens: Int? = nil
    ) {
        self.messages = messages
        self.enabledTools = enabledTools
        self.sessionID = sessionID
        self.assistantMessageID = assistantMessageID
        self.parentID = parentID
        self.imageBase64 = imageBase64
        self.reasoningEffort = reasoningEffort
        self.enableThinking = enableThinking
        self.maxTokens = maxTokens
    }

    enum CodingKeys: String, CodingKey {
        case messages
        case stream
        case enableTools = "enable_tools"
        case enabledTools = "enabled_tools"
        case sessionID = "session_id"
        case assistantMessageID = "assistant_message_id"
        case parentID = "parent_id"
        case imageBase64 = "image_base64"
        case reasoningEffort = "reasoning_effort"
        case enableThinking = "enable_thinking"
        case maxTokens = "max_tokens"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(messages, forKey: .messages)
        try container.encode(stream, forKey: .stream)
        try container.encode(enableTools, forKey: .enableTools)
        try container.encode(enabledTools, forKey: .enabledTools)
        try container.encodeIfPresent(sessionID, forKey: .sessionID)
        try container.encodeIfPresent(assistantMessageID, forKey: .assistantMessageID)
        try container.encodeIfPresent(parentID, forKey: .parentID)
        try container.encodeIfPresent(imageBase64, forKey: .imageBase64)
        try container.encodeIfPresent(reasoningEffort, forKey: .reasoningEffort)
        try container.encodeIfPresent(enableThinking, forKey: .enableThinking)
        try container.encodeIfPresent(maxTokens, forKey: .maxTokens)
    }
}
