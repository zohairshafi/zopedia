import Foundation

public struct MaintenanceSchedule: Decodable, Identifiable, Hashable, Sendable {
    public let id: String
    public var enabled: Bool
    public let intervalType: String
    public let withWebFill: Bool
    public let runHour: Int?
    public let runDow: Int?
    public let runDom: Int?
    public let createdAt: Date?
    public let lastRunAt: Date?
    public let nextRunAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case enabled
        case intervalType = "interval_type"
        case withWebFill = "with_web_fill"
        case runHour = "run_hour"
        case runDow = "run_dow"
        case runDom = "run_dom"
        case createdAt = "created_at"
        case lastRunAt = "last_run_at"
        case nextRunAt = "next_run_at"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id) ?? ""
        enabled = Self.flexibleBool(container, key: .enabled) ?? false
        intervalType = try container.decodeIfPresent(String.self, forKey: .intervalType) ?? "daily"
        withWebFill = Self.flexibleBool(container, key: .withWebFill) ?? false
        runHour = try container.decodeIfPresent(Int.self, forKey: .runHour)
        runDow = try container.decodeIfPresent(Int.self, forKey: .runDow)
        runDom = try container.decodeIfPresent(Int.self, forKey: .runDom)
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
        lastRunAt = try container.decodeIfPresent(Date.self, forKey: .lastRunAt)
        nextRunAt = try container.decodeIfPresent(Date.self, forKey: .nextRunAt)
    }

    /// The store returns SQLite 0/1 values for these flags.
    private static func flexibleBool(
        _ container: KeyedDecodingContainer<CodingKeys>,
        key: CodingKeys
    ) -> Bool? {
        if let value = try? container.decodeIfPresent(Bool.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return value != 0
        }
        return nil
    }
}

public struct MaintenanceScheduleListResponse: Decodable, Sendable {
    public let schedules: [MaintenanceSchedule]
}

public struct MaintenanceScheduleCreateResponse: Decodable, Sendable {
    public let id: String
    public let nextRunAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case nextRunAt = "next_run_at"
    }
}

public struct MaintenanceScheduleCreateRequest: Encodable, Sendable {
    public let intervalType: String
    public let withWebFill: Bool
    public let runHour: Int?
    public let runDow: Int?
    public let runDom: Int?

    public init(
        intervalType: String,
        withWebFill: Bool = false,
        runHour: Int? = nil,
        runDow: Int? = nil,
        runDom: Int? = nil
    ) {
        self.intervalType = intervalType
        self.withWebFill = withWebFill
        self.runHour = runHour
        self.runDow = runDow
        self.runDom = runDom
    }

    enum CodingKeys: String, CodingKey {
        case intervalType = "interval_type"
        case withWebFill = "with_web_fill"
        case runHour = "run_hour"
        case runDow = "run_dow"
        case runDom = "run_dom"
    }
}

public struct MaintenanceScheduleUpdateRequest: Encodable, Sendable {
    public var enabled: Bool?
    public var intervalType: String?
    public var withWebFill: Bool?
    public var runHour: Int?
    public var runDow: Int?
    public var runDom: Int?

    public init(
        enabled: Bool? = nil,
        intervalType: String? = nil,
        withWebFill: Bool? = nil,
        runHour: Int? = nil,
        runDow: Int? = nil,
        runDom: Int? = nil
    ) {
        self.enabled = enabled
        self.intervalType = intervalType
        self.withWebFill = withWebFill
        self.runHour = runHour
        self.runDow = runDow
        self.runDom = runDom
    }

    enum CodingKeys: String, CodingKey {
        case enabled
        case intervalType = "interval_type"
        case withWebFill = "with_web_fill"
        case runHour = "run_hour"
        case runDow = "run_dow"
        case runDom = "run_dom"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(enabled, forKey: .enabled)
        try container.encodeIfPresent(intervalType, forKey: .intervalType)
        try container.encodeIfPresent(withWebFill, forKey: .withWebFill)
        try container.encodeIfPresent(runHour, forKey: .runHour)
        try container.encodeIfPresent(runDow, forKey: .runDow)
        try container.encodeIfPresent(runDom, forKey: .runDom)
    }
}

public struct MaintenanceRunNowResponse: Decodable, Sendable {
    public let status: String
    public let result: JSONValue?
}
