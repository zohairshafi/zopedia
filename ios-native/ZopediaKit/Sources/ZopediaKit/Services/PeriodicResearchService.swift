import Foundation

public struct PeriodicResearchService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func list() async throws -> PeriodicResearchListResponse {
        try await client.get("api/research/periodic")
    }

    public func detail(id: String) async throws -> PeriodicResearchDetail {
        try await client.get("api/research/periodic/\(id)")
    }

    public func create(_ request: PeriodicResearchRequest) async throws -> PeriodicCreateResponse {
        try await client.post("api/research/periodic", body: request)
    }

    public func update(id: String, request: PeriodicResearchRequest) async throws -> PeriodicCreateResponse {
        try await client.request(
            method: "PUT",
            path: "api/research/periodic/\(id)",
            body: request
        )
    }

    public func setEnabled(id: String, enabled: Bool) async throws -> PeriodicToggleResponse {
        try await client.patch(
            "api/research/periodic/\(id)",
            body: PeriodicToggleRequest(enabled: enabled)
        )
    }

    public func delete(id: String) async throws {
        let _: StatusResponse = try await client.delete("api/research/periodic/\(id)")
    }

    public func runNow(id: String) async throws {
        let _: StatusResponse = try await client.post(
            "api/research/periodic/\(id)/run-now"
        )
    }
}
