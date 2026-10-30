import Foundation
import Observation
import os
import ZopediaKit

@MainActor
@Observable
final class AppEnvironment {
    enum Phase: Equatable {
        case launching
        case connect
        case changePassword
        case ready
    }

    private static let logger = Logger(subsystem: "com.zopedia.client", category: "app")

    private(set) var phase: Phase = .launching
    private(set) var health: HealthResponse?
    private(set) var permissions: Permissions?
    private(set) var serverURL: String?
    private(set) var subject: String?
    private(set) var client: APIClient?
    private(set) var auth: AuthSession?
    private(set) var chat: ChatService?
    private(set) var wiki: WikiService?
    private(set) var attachments: AttachmentService?
    private(set) var research: ResearchService?
    private(set) var periodicResearch: PeriodicResearchService?
    private(set) var trading: TradingService?
    private(set) var maintenance: MaintenanceService?
    private(set) var wikiEnv: WikiEnvService?
    private(set) var cache: ThreadCache?

    let chatOptions = ChatOptionsStore()
    let wikiUploads = WikiUploadMonitor()

    var canManageAdvanced: Bool {
        permissions?.isAdmin == true || health?.authDisabled == true
    }

    var errorMessage: String?
    var isBusy = false

    let serverStore: ServerStore
    private let tokenStore: TokenStoring
    private var service: AuthService?

    init(
        serverStore: ServerStore = ServerStore(),
        tokenStore: TokenStoring = KeychainTokenStore()
    ) {
        self.serverStore = serverStore
        self.tokenStore = tokenStore
    }

    func start() async {
        guard phase == .launching else { return }

        guard let saved = serverStore.serverURL,
              let url = try? ServerURL.normalize(saved) else {
            phase = .connect
            return
        }

        configure(serverURL: url)
        do {
            let restored = try await auth?.restore() ?? false
            guard restored else {
                phase = .connect
                return
            }
            // Permissions are persisted at login. Without this, a restored
            // session has no is_admin flag and the Advanced settings stay hidden.
            permissions = serverStore.permissions
            try await resolveSubject()
            configureChat()

            if serverStore.mustChangePassword {
                phase = .changePassword
                return
            }
            phase = .ready
            await refreshHealth()
        } catch APIError.unauthorized {
            await auth?.signOut()
            phase = .connect
        } catch {
            errorMessage = Self.message(for: error)
            phase = .connect
        }
    }

    func connect(urlText: String, username: String, password: String) async {
        isBusy = true
        defer { isBusy = false }
        errorMessage = nil

        do {
            let url = try ServerURL.normalize(urlText)
            configure(serverURL: url)

            guard let service else { throw APIError.invalidURL }
            let status = try await service.status()
            guard status.initialized else {
                throw APIError.server(
                    "This server has not been initialized yet. Open it in a browser first."
                )
            }

            let username = username.trimmingCharacters(in: .whitespacesAndNewlines)
            let effectiveUsername = username.isEmpty ? "local-user" : username
            let effectivePassword = status.authDisabled && password.isEmpty ? "local-user" : password

            if !status.authDisabled {
                guard !username.isEmpty else { throw APIError.server("Enter your username.") }
                guard !password.isEmpty else { throw APIError.server("Enter your password.") }
            }

            let response = try await service.login(
                username: effectiveUsername,
                password: effectivePassword
            )

            try await auth?.setSession(response)
            permissions = response.permissions
            serverStore.serverURL = url.absoluteString
            serverStore.permissions = response.permissions
            serverStore.mustChangePassword = response.mustChangePassword
            serverStore.remember(url: url.absoluteString, username: effectiveUsername)
            serverURL = url.absoluteString

            try await resolveSubject(fallback: effectiveUsername)
            configureChat()

            if response.mustChangePassword {
                phase = .changePassword
            } else {
                phase = .ready
                await refreshHealth()
            }
        } catch {
            errorMessage = Self.message(for: error)
            phase = .connect
        }
    }

    func changePassword(current: String, new: String) async {
        guard let service else { return }
        isBusy = true
        defer { isBusy = false }
        errorMessage = nil

        do {
            let response = try await service.changePassword(current: current, new: new)
            try await auth?.setSession(response)
            serverStore.mustChangePassword = false
            serverStore.permissions = response.permissions
            permissions = response.permissions
            phase = .ready
            await refreshHealth()
        } catch {
            errorMessage = Self.message(for: error)
        }
    }

    func refreshHealth() async {
        guard let service else { return }
        health = try? await service.health()
    }

    func refreshThreads() async throws -> [ChatThread] {
        guard let chat, let cache else { throw APIError.invalidURL }
        let response = try await chat.listThreads()
        return await cache.replaceIndex(with: response.threads)
    }

    func disconnect() async {
        await auth?.signOut()
        serverStore.clearSession()
        client = nil
        auth = nil
        service = nil
        chat = nil
        wiki = nil
        attachments = nil
        research = nil
        periodicResearch = nil
        trading = nil
        maintenance = nil
        wikiEnv = nil
        cache = nil
        health = nil
        permissions = nil
        serverURL = nil
        subject = nil
        errorMessage = nil
        phase = .connect
    }

    private func resolveSubject(fallback: String? = nil) async throws {
        guard let service else { throw APIError.invalidURL }
        do {
            let profile = try await service.profile()
            subject = profile.username
            serverStore.subject = profile.username
        } catch let error as APIError {
            if error == .unauthorized || error == .passwordChangeRequired {
                throw error
            }
            guard let saved = serverStore.subject ?? fallback else { throw error }
            subject = saved
            serverStore.subject = saved
        }
    }

    private func configure(serverURL url: URL) {
        let auth = AuthSession(baseURL: url, store: tokenStore)
        let client = APIClient(baseURL: url, auth: auth)
        self.auth = auth
        self.client = client
        self.service = AuthService(client: client)
        self.serverURL = url.absoluteString
    }

    var cacheRoot: URL {
        FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        )[0]
        .appendingPathComponent("Zopedia", isDirectory: true)
        .appendingPathComponent("cache", isDirectory: true)
    }

    private func configureChat() {
        guard let client, let serverURL, let subject else { return }
        chat = ChatService(client: client)
        wiki = WikiService(client: client)
        attachments = AttachmentService(client: client)
        research = ResearchService(client: client)
        periodicResearch = PeriodicResearchService(client: client)
        trading = TradingService(client: client)
        maintenance = MaintenanceService(client: client)
        wikiEnv = WikiEnvService(client: client)

        do {
            cache = try ThreadCache(
                root: cacheRoot,
                serverURL: serverURL,
                subject: subject
            )
        } catch {
            cache = nil
            Self.logger.error(
                "cache unavailable: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private static func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
