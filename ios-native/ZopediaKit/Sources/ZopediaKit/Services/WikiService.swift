import Foundation

public struct WikiService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func files() async throws -> WikiFilesResponse {
        try await client.get("api/inference/wiki/files")
    }

    /// Fetch a page's raw Markdown. This endpoint returns text, not JSON.
    public func page(path: String) async throws -> String {
        let data = try await client.send(
            APIRequest(
                method: "GET",
                path: "api/inference/wiki-file",
                query: [URLQueryItem(name: "path", value: path)]
            )
        )
        guard let text = String(data: data, encoding: .utf8) else {
            throw APIError.decoding("The wiki page is not valid UTF-8.")
        }
        return text
    }

    /// `save_answer` stays false so searching does not create a page.
    public func query(question: String) async throws -> WikiQueryResponse {
        try await client.post(
            "api/inference/wiki/query",
            body: WikiQueryBody(question: question, saveAnswer: false)
        )
    }

    public func ingest(url: String) async throws -> WikiIngestResponse {
        try await client.post(
            "api/inference/wiki/ingest",
            body: WikiIngestBody(sourcePath: url, maxPendingRawFiles: 0),
            timeout: 1800
        )
    }

    /// Export a transcript to the wiki raw folder. The server writes the file
    /// and enqueues ingestion durably, so the request only needs to complete.
    public func saveChatHistory(
        threadID: String,
        title: String?,
        messages: [ChatMessage]
    ) async throws -> WikiChatHistorySaveResponse {
        try await client.post(
            "api/inference/wiki/chat-history/save",
            body: WikiChatHistoryBody(
                threadID: threadID,
                threadTitle: title,
                messages: messages.map { message in
                    WikiChatHistoryMessagePayload(
                        role: message.role.rawValue,
                        content: message.visibleText,
                        reasoningContent: message.reasoningContent
                    )
                }
            )
        )
    }
}

public struct WikiChatHistorySaveResponse: Decodable, Sendable {
    public let status: String
    public let operation: String
    public let threadID: String
    public let filePath: String
    public let relativePath: String
    public let messageCount: Int
    public let watcherEnabled: Bool
    public let ingestedImmediately: Bool

    enum CodingKeys: String, CodingKey {
        case status
        case operation
        case threadID = "thread_id"
        case filePath = "file_path"
        case relativePath = "relative_path"
        case messageCount = "message_count"
        case watcherEnabled = "watcher_enabled"
        case ingestedImmediately = "ingested_immediately"
    }
}

private struct WikiChatHistoryBody: Encodable {
    let threadID: String
    let threadTitle: String?
    let messages: [WikiChatHistoryMessagePayload]

    enum CodingKeys: String, CodingKey {
        case threadID = "thread_id"
        case threadTitle = "thread_title"
        case messages
    }
}

private struct WikiChatHistoryMessagePayload: Encodable {
    let role: String
    let content: String
    let reasoningContent: String?

    enum CodingKeys: String, CodingKey {
        case role
        case content
        case reasoningContent = "reasoning_content"
    }
}

private struct WikiQueryBody: Encodable {
    let question: String
    let saveAnswer: Bool

    enum CodingKeys: String, CodingKey {
        case question
        case saveAnswer = "save_answer"
    }
}

private struct WikiIngestBody: Encodable {
    let sourcePath: String
    let maxPendingRawFiles: Int

    enum CodingKeys: String, CodingKey {
        case sourcePath = "source_path"
        case maxPendingRawFiles = "max_pending_raw_files"
    }
}
