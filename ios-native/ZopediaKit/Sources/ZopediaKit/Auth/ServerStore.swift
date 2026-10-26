import Foundation

public struct RecentServer: Codable, Hashable, Sendable, Identifiable {
    public var url: String
    public var username: String

    public var id: String { url }

    public init(url: String, username: String) {
        self.url = url
        self.username = username
    }
}

/// Non-secret client state. Tokens never live here.
public final class ServerStore: @unchecked Sendable {
    private let defaults: UserDefaults
    private let serverKey = "zopedia.server.url"
    private let recentKey = "zopedia.recent.servers"
    private let permissionsKey = "zopedia.permissions"
    private let mustChangeKey = "zopedia.must_change_password"
    private let subjectKey = "zopedia.subject"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public var serverURL: String? {
        get { defaults.string(forKey: serverKey) }
        set {
            if let newValue {
                defaults.set(newValue, forKey: serverKey)
            } else {
                defaults.removeObject(forKey: serverKey)
            }
        }
    }

    public var recentServers: [RecentServer] {
        guard let data = defaults.data(forKey: recentKey),
              let decoded = try? JSONDecoder().decode([RecentServer].self, from: data) else {
            return []
        }
        return decoded
    }

    public func remember(url: String, username: String) {
        var servers = recentServers.filter { $0.url != url }
        servers.insert(RecentServer(url: url, username: username), at: 0)
        if servers.count > 5 { servers = Array(servers.prefix(5)) }
        if let data = try? JSONEncoder().encode(servers) {
            defaults.set(data, forKey: recentKey)
        }
    }

    public func removeRecent(url: String) {
        let servers = recentServers.filter { $0.url != url }
        if let data = try? JSONEncoder().encode(servers) {
            defaults.set(data, forKey: recentKey)
        }
    }

    public var permissions: Permissions? {
        get {
            guard let data = defaults.data(forKey: permissionsKey) else { return nil }
            return try? JSONDecoder().decode(Permissions.self, from: data)
        }
        set {
            if let newValue, let data = try? JSONEncoder().encode(newValue) {
                defaults.set(data, forKey: permissionsKey)
            } else {
                defaults.removeObject(forKey: permissionsKey)
            }
        }
    }

    public var mustChangePassword: Bool {
        get { defaults.bool(forKey: mustChangeKey) }
        set { defaults.set(newValue, forKey: mustChangeKey) }
    }

    public var subject: String? {
        get { defaults.string(forKey: subjectKey) }
        set {
            if let newValue {
                defaults.set(newValue, forKey: subjectKey)
            } else {
                defaults.removeObject(forKey: subjectKey)
            }
        }
    }

    public func clearSession() {
        serverURL = nil
        permissions = nil
        mustChangePassword = false
        subject = nil
    }
}
