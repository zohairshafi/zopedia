import Foundation

/// Owns the bearer tokens and performs exactly one refresh for any number of
/// concurrent 401s.
public actor AuthSession {
    private let baseURL: URL
    private let session: URLSession
    private let store: TokenStoring
    private var tokens: AuthTokens?
    private var refreshTask: Task<AuthTokens, Error>?

    public private(set) var permissions: Permissions?
    public private(set) var mustChangePassword = false

    public init(
        baseURL: URL,
        store: TokenStoring,
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.store = store
        self.session = session
    }

    public var accessToken: String? { tokens?.accessToken }
    public var hasTokens: Bool { tokens != nil }

    @discardableResult
    public func restore() throws -> Bool {
        tokens = try store.load()
        return tokens != nil
    }

    public func setSession(_ response: TokenResponse) throws {
        let newTokens = AuthTokens(
            accessToken: response.accessToken,
            refreshToken: response.refreshToken
        )
        try store.save(newTokens)
        tokens = newTokens
        permissions = response.permissions ?? permissions
        mustChangePassword = response.mustChangePassword
    }

    public func updatePermissions(_ value: Permissions?) {
        permissions = value
    }

    public func updateMustChangePassword(_ value: Bool) {
        mustChangePassword = value
    }

    public func signOut() {
        try? store.clear()
        tokens = nil
        refreshTask?.cancel()
        refreshTask = nil
    }

    /// Single-flight refresh. Concurrent callers share one network request.
    public func refreshIfNeeded() async throws -> AuthTokens {
        if let refreshTask {
            return try await refreshTask.value
        }
        guard let refreshToken = tokens?.refreshToken else {
            throw APIError.unauthorized
        }

        let task = Task { [baseURL, session, store] () -> AuthTokens in
            try await Self.performRefresh(
                baseURL: baseURL,
                session: session,
                store: store,
                refreshToken: refreshToken
            )
        }
        refreshTask = task
        defer { refreshTask = nil }

        do {
            return try await task.value
        } catch {
            signOut()
            throw error
        }
    }

    private static func performRefresh(
        baseURL: URL,
        session: URLSession,
        store: TokenStoring,
        refreshToken: String
    ) async throws -> AuthTokens {
        guard let url = baseURL.zopediaURL(path: "api/auth/refresh") else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(RefreshRequest(refreshToken: refreshToken))

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .cancelled {
            throw APIError.cancelled
        } catch {
            throw APIError.transport(error.localizedDescription)
        }

        guard let http = response as? HTTPURLResponse else {
            throw APIError.transport("The server returned a non-HTTP response.")
        }
        if http.statusCode == 401 || http.statusCode == 403 {
            throw APIError.unauthorized
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = HTTPErrorDetail.from(data) ?? "HTTP \(http.statusCode)"
            throw APIError.http(status: http.statusCode, detail: detail)
        }

        let decoded: TokenResponse
        do {
            decoded = try JSONDecoder().decode(TokenResponse.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }

        let refreshed = AuthTokens(
            accessToken: decoded.accessToken,
            refreshToken: decoded.refreshToken
        )
        try store.save(refreshed)
        return refreshed
    }
}
