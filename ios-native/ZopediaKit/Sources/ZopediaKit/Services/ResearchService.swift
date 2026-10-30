import Foundation

public struct ResearchService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    /// Interactive research. The server cancels the run if this stream disconnects.
    public func stream(config: ResearchConfig) -> AsyncThrowingStream<ResearchEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let body = try JSONEncoder().encode(config)
                    let payloads = await client.streamSSEPayloads(
                        APIRequest(
                            method: "POST",
                            path: "api/research/stream",
                            body: body,
                            contentType: "application/json"
                        ),
                        timeout: 1800
                    )

                    for try await payload in payloads {
                        let event = try ResearchStreamDecoder.decode(payload)
                        continuation.yield(event)
                        if event == .done { break }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish(throwing: APIError.cancelled)
                } catch let error as APIError {
                    continuation.finish(throwing: error)
                } catch {
                    continuation.finish(throwing: APIError.transport(error.localizedDescription))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    public func approve(
        sessionID: String,
        approvedURLs: [String],
        rejectedURLs: [String]
    ) async throws {
        let _: StatusResponse = try await client.post(
            "api/research/approve",
            body: ResearchApprovalBody(
                sessionID: sessionID,
                approvedURLs: approvedURLs,
                rejectedURLs: rejectedURLs
            )
        )
    }

    public func cancel(sessionID: String) async throws {
        let _: StatusResponse = try await client.post(
            "api/research/cancel",
            body: ResearchCancelBody(sessionID: sessionID)
        )
    }
}

private struct ResearchApprovalBody: Encodable {
    let sessionID: String
    let approvedURLs: [String]
    let rejectedURLs: [String]

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case approvedURLs = "approved_urls"
        case rejectedURLs = "rejected_urls"
    }
}

private struct ResearchCancelBody: Encodable {
    let sessionID: String

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
    }
}
