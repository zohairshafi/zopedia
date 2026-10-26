import Foundation

public struct ChatService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func listThreads() async throws -> ThreadListResponse {
        try await client.get("api/chat/threads")
    }

    public func getThread(_ id: String) async throws -> ThreadDetailResponse {
        try await client.get("api/chat/threads/\(id)")
    }

    public func saveThread(
        id: String,
        title: String?,
        messages: [ChatMessage]
    ) async throws -> SaveThreadResponse {
        try await client.post(
            "api/chat/threads",
            body: SaveThreadBody(
                threadID: id,
                title: title,
                messages: messages.map { MessagePayload(message: $0) }
            )
        )
    }

    public func appendMessages(
        threadID: String,
        title: String?,
        messages: [ChatMessage]
    ) async throws -> AppendMessagesResponse {
        try await client.post(
            "api/chat/threads/\(threadID)/messages",
            body: AppendBody(
                threadID: threadID,
                title: title,
                messages: messages.map { MessagePayload(message: $0) }
            )
        )
    }

    public func renameThread(id: String, title: String) async throws {
        let _: StatusResponse = try await client.patch(
            "api/chat/threads/\(id)",
            body: RenameBody(title: title)
        )
    }

    public func deleteThread(id: String) async throws {
        let _: StatusResponse = try await client.delete("api/chat/threads/\(id)")
    }

    public func deleteMessage(threadID: String, messageID: String) async throws {
        let _: StatusResponse = try await client.delete(
            "api/chat/threads/\(threadID)/messages/\(messageID)"
        )
    }

    /// Note the `/v1` prefix: this endpoint lives on the chat router.
    public func generateTitle(userText: String, assistantText: String) async throws -> String {
        let response: GenerateTitleResponse = try await client.post(
            "v1/api/chat/generate-title",
            body: GenerateTitleBody(userText: userText, assistantText: assistantText)
        )
        return response.title
    }

    public func answerQuestion(
        sessionID: String,
        toolCallID: String,
        answer: String
    ) async throws {
        let _: StatusResponse = try await client.post(
            "v1/api/chat/tool-answer",
            body: ToolAnswerBody(sessionID: sessionID, toolCallID: toolCallID, answer: answer)
        )
    }

    public func decideApproval(
        sessionID: String,
        toolCallID: String,
        approve: Bool
    ) async throws {
        let _: StatusResponse = try await client.post(
            "v1/api/chat/tool-approval",
            body: ToolApprovalBody(
                sessionID: sessionID,
                toolCallID: toolCallID,
                decision: approve ? "approve" : "reject"
            )
        )
    }
}

private struct GenerateTitleBody: Encodable {
    let userText: String
    let assistantText: String
}

private struct GenerateTitleResponse: Decodable {
    let title: String
}

private struct ToolAnswerBody: Encodable {
    let sessionID: String
    let toolCallID: String
    let answer: String

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case toolCallID = "tool_call_id"
        case answer
    }
}

private struct ToolApprovalBody: Encodable {
    let sessionID: String
    let toolCallID: String
    let decision: String

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case toolCallID = "tool_call_id"
        case decision
    }
}

private struct SaveThreadBody: Encodable {
    let threadID: String
    let title: String?
    let messages: [MessagePayload]

    enum CodingKeys: String, CodingKey {
        case threadID = "thread_id"
        case title
        case messages
    }
}

private struct AppendBody: Encodable {
    let threadID: String
    let title: String?
    let messages: [MessagePayload]

    enum CodingKeys: String, CodingKey {
        case threadID = "thread_id"
        case title
        case messages
    }
}

private struct RenameBody: Encodable {
    let title: String
}
