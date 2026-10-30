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
