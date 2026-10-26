import Foundation

public struct AuthService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func status() async throws -> AuthStatus {
        try await client.get("api/auth/status", requiresAuth: false)
    }

    public func login(username: String, password: String) async throws -> TokenResponse {
        try await client.post(
            "api/auth/login",
            body: LoginRequest(username: username, password: password),
            requiresAuth: false
        )
    }

    public func health() async throws -> HealthResponse {
        try await client.get("api/health", requiresAuth: false)
    }

    public func profile() async throws -> ProfileResponse {
        try await client.get("api/auth/profile")
    }

    public func changePassword(
        current: String,
        new: String
    ) async throws -> TokenResponse {
        try await client.post(
            "api/auth/change-password",
            body: ChangePasswordRequest(currentPassword: current, newPassword: new)
        )
    }
}
