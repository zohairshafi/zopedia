import Foundation

public struct Permissions: Codable, Hashable, Sendable {
    public var canSaveChatHistory: Bool
    public var canUploadFiles: Bool
    public var isAdmin: Bool

    public init(
        canSaveChatHistory: Bool = false,
        canUploadFiles: Bool = false,
        isAdmin: Bool = false
    ) {
        self.canSaveChatHistory = canSaveChatHistory
        self.canUploadFiles = canUploadFiles
        self.isAdmin = isAdmin
    }

    enum CodingKeys: String, CodingKey {
        case canSaveChatHistory = "can_save_chat_history"
        case canUploadFiles = "can_upload_files"
        case isAdmin = "is_admin"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        canSaveChatHistory = try container.decodeIfPresent(Bool.self, forKey: .canSaveChatHistory) ?? false
        canUploadFiles = try container.decodeIfPresent(Bool.self, forKey: .canUploadFiles) ?? false
        isAdmin = try container.decodeIfPresent(Bool.self, forKey: .isAdmin) ?? false
    }
}

public struct AuthTokens: Codable, Hashable, Sendable {
    public var accessToken: String
    public var refreshToken: String

    public init(accessToken: String, refreshToken: String) {
        self.accessToken = accessToken
        self.refreshToken = refreshToken
    }
}

public struct TokenResponse: Decodable, Sendable {
    public let accessToken: String
    public let refreshToken: String
    public let mustChangePassword: Bool
    public let permissions: Permissions?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case mustChangePassword = "must_change_password"
        case permissions
    }
}

public struct AuthStatus: Decodable, Sendable {
    public let initialized: Bool
    public let requiresPasswordChange: Bool
    public let authDisabled: Bool

    enum CodingKeys: String, CodingKey {
        case initialized
        case requiresPasswordChange = "requires_password_change"
        case authDisabled = "auth_disabled"
    }
}

public struct HealthResponse: Decodable, Sendable {
    public let status: String
    public let llmConfigured: Bool
    public let llmProvider: String
    public let llmModel: String
    public let authDisabled: Bool

    enum CodingKeys: String, CodingKey {
        case status
        case llmConfigured = "llm_configured"
        case llmProvider = "llm_provider"
        case llmModel = "llm_model"
        case authDisabled = "auth_disabled"
    }
}

public struct ProfileResponse: Decodable, Sendable {
    public let username: String
    public let displayName: String?

    enum CodingKeys: String, CodingKey {
        case username
        case displayName = "display_name"
    }
}

public struct LoginRequest: Encodable, Sendable {
    public let username: String
    public let password: String
}

public struct RefreshRequest: Encodable, Sendable {
    public let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

public struct ChangePasswordRequest: Encodable, Sendable {
    public let currentPassword: String
    public let newPassword: String

    enum CodingKeys: String, CodingKey {
        case currentPassword = "current_password"
        case newPassword = "new_password"
    }
}
