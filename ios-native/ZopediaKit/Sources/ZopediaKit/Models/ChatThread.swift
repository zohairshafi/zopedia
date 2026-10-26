import Foundation

public struct ChatThread: Identifiable, Codable, Hashable, Sendable {
    public let id: String
    public var title: String
    public var createdAt: Date
    public var updatedAt: Date
    public var messageCount: Int

    public init(
        id: String,
        title: String,
        createdAt: Date,
        updatedAt: Date,
        messageCount: Int
    ) {
        self.id = id
        self.title = title
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.messageCount = messageCount
    }

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messageCount = "message_count"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "New Chat"
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
            ?? Date(timeIntervalSince1970: 0)
        updatedAt = try container.decodeIfPresent(Date.self, forKey: .updatedAt)
            ?? createdAt
        messageCount = try container.decodeIfPresent(Int.self, forKey: .messageCount) ?? 0
    }
}

public struct ThreadListResponse: Decodable, Sendable {
    public let threads: [ChatThread]
    public let subject: String
}

public struct ThreadDetailResponse: Decodable, Sendable {
    public let thread: ChatThread
    public let messages: [ChatMessage]
}

public struct AppendMessagesResponse: Decodable, Sendable {
    public let appended: Int
    public let insertedIDs: [String]

    enum CodingKeys: String, CodingKey {
        case appended
        case insertedIDs = "inserted_ids"
    }
}

public struct StatusResponse: Decodable, Sendable {
    public let status: String
}

public struct SaveThreadResponse: Decodable, Sendable {
    public let status: String
    public let threadID: String

    enum CodingKeys: String, CodingKey {
        case status
        case threadID = "thread_id"
    }
}
