import Foundation

public struct WikiEnvService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func config() async throws -> WikiEnvConfig {
        try await client.get("api/inference/wiki/env")
    }

    public func set(_ request: WikiEnvSetRequest) async throws -> WikiEnvSetResponse {
        try await client.post("api/inference/wiki/env", body: request)
    }
}
