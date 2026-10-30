import Foundation

public struct MaintenanceService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func list() async throws -> MaintenanceScheduleListResponse {
        try await client.get("api/inference/wiki/maintenance/scheduled")
    }

    public func create(
        _ request: MaintenanceScheduleCreateRequest
    ) async throws -> MaintenanceScheduleCreateResponse {
        try await client.post("api/inference/wiki/maintenance/scheduled", body: request)
    }

    public func update(
        id: String,
        request: MaintenanceScheduleUpdateRequest
    ) async throws {
        let _: StatusResponse = try await client.request(
            method: "PUT",
            path: "api/inference/wiki/maintenance/scheduled/\(id)",
            body: request
        )
    }

    public func delete(id: String) async throws {
        let _: StatusResponse = try await client.delete(
            "api/inference/wiki/maintenance/scheduled/\(id)"
        )
    }

    /// The server runs the whole pipeline before responding.
    public func runNow(id: String) async throws -> MaintenanceRunNowResponse {
        try await client.post(
            "api/inference/wiki/maintenance/scheduled/\(id)/run-now",
            timeout: 3600
        )
    }
}
