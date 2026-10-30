import Foundation

public struct PendingTradeApproval: Decodable, Identifiable, Hashable, Sendable {
    public let id: String
    public let source: String?
    public let configID: String?
    public let threadID: String?
    public let order: [String: JSONValue]
    public let rationale: String?
    public let status: String
    public let createdAt: Date?
    public let expiresAt: Date?
    public let decidedAt: Date?
    public let result: JSONValue?

    enum CodingKeys: String, CodingKey {
        case id
        case source
        case configID = "config_id"
        case threadID = "thread_id"
        case order
        case rationale
        case status
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case decidedAt = "decided_at"
        case result
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id) ?? ""
        source = try container.decodeIfPresent(String.self, forKey: .source)
        configID = try container.decodeIfPresent(String.self, forKey: .configID)
        threadID = try container.decodeIfPresent(String.self, forKey: .threadID)
        order = try container.decodeIfPresent([String: JSONValue].self, forKey: .order) ?? [:]
        rationale = try container.decodeIfPresent(String.self, forKey: .rationale)
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "pending"
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
        expiresAt = try container.decodeIfPresent(Date.self, forKey: .expiresAt)
        decidedAt = try container.decodeIfPresent(Date.self, forKey: .decidedAt)
        result = try container.decodeIfPresent(JSONValue.self, forKey: .result)
    }

    public var side: String {
        order["side"]?.stringValue?.uppercased() ?? ""
    }

    public var symbol: String {
        order["symbol"]?.stringValue?.uppercased() ?? ""
    }

    public var quantity: String {
        guard let value = order["qty"] else { return "" }
        if let text = value.stringValue { return text }
        if let integer = value.intValue { return String(integer) }
        if case .double(let double) = value { return String(double) }
        return ""
    }

    public var orderType: String {
        order["type"]?.stringValue?.uppercased() ?? ""
    }
}

public struct PendingApprovalsResponse: Decodable, Sendable {
    public let approvals: [PendingTradeApproval]
    public let pendingCount: Int

    enum CodingKeys: String, CodingKey {
        case approvals
        case pendingCount = "pending_count"
    }
}

public struct TradeDecisionResponse: Decodable, Sendable {
    public let status: String
    public let approvalID: String?
    public let order: JSONValue?

    enum CodingKeys: String, CodingKey {
        case status
        case approvalID = "approval_id"
        case order
    }
}
