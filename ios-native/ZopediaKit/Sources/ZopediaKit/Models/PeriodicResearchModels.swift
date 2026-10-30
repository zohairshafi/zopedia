import Foundation

public struct PeriodicResearchSummary: Decodable, Identifiable, Hashable, Sendable {
    public let id: String
    public let topic: String
    public let intervalType: String
    public var enabled: Bool
    public let runHour: Int?
    public let runDow: Int?
    public let runDom: Int?
    public let lastRunAt: Date?
    public let nextRunAt: Date?
    public let createdAt: Date?
    public let trustedCount: Int
    public let rounds: Int
    public let sourcesPerRound: Int

    enum CodingKeys: String, CodingKey {
        case id
        case topic
        case intervalType = "interval_type"
        case enabled
        case runHour = "run_hour"
        case runDow = "run_dow"
        case runDom = "run_dom"
        case lastRunAt = "last_run_at"
        case nextRunAt = "next_run_at"
        case createdAt = "created_at"
        case trustedCount = "trusted_count"
        case rounds
        case sourcesPerRound = "sources_per_round"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id) ?? ""
        topic = try container.decodeIfPresent(String.self, forKey: .topic) ?? ""
        intervalType = try container.decodeIfPresent(String.self, forKey: .intervalType) ?? "daily"
        enabled = try container.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        runHour = try container.decodeIfPresent(Int.self, forKey: .runHour)
        runDow = try container.decodeIfPresent(Int.self, forKey: .runDow)
        runDom = try container.decodeIfPresent(Int.self, forKey: .runDom)
        lastRunAt = try container.decodeIfPresent(Date.self, forKey: .lastRunAt)
        nextRunAt = try container.decodeIfPresent(Date.self, forKey: .nextRunAt)
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
        trustedCount = try container.decodeIfPresent(Int.self, forKey: .trustedCount) ?? 0
        rounds = try container.decodeIfPresent(Int.self, forKey: .rounds) ?? 3
        sourcesPerRound = try container.decodeIfPresent(Int.self, forKey: .sourcesPerRound) ?? 10
    }
}

public struct PeriodicResearchDetail: Decodable, Identifiable, Sendable {
    public let id: String
    public let topic: String
    public let intervalType: String
    public let enabled: Bool
    public let runHour: Int?
    public let runDow: Int?
    public let runDom: Int?
    public let lastRunAt: Date?
    public let nextRunAt: Date?
    public let createdAt: Date?
    public let rounds: Int
    public let sourcesPerRound: Int
    public let trustedSources: [String]
    public let blockedSources: [String]
    public let researchDepth: String
    public let alpacaTradingEnabled: Bool
    public let sourceTypes: [String]
    public let timelimit: String

    enum CodingKeys: String, CodingKey {
        case id
        case topic
        case intervalType = "interval_type"
        case enabled
        case runHour = "run_hour"
        case runDow = "run_dow"
        case runDom = "run_dom"
        case lastRunAt = "last_run_at"
        case nextRunAt = "next_run_at"
        case createdAt = "created_at"
        case rounds
        case sourcesPerRound = "sources_per_round"
        case trustedSources = "trusted_sources"
        case blockedSources = "blocked_sources"
        case researchDepth = "research_depth"
        case alpacaTradingEnabled = "alpaca_trading_enabled"
        case sourceTypes = "source_types"
        case timelimit
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id) ?? ""
        topic = try container.decodeIfPresent(String.self, forKey: .topic) ?? ""
        intervalType = try container.decodeIfPresent(String.self, forKey: .intervalType) ?? "daily"
        enabled = try container.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        runHour = try container.decodeIfPresent(Int.self, forKey: .runHour)
        runDow = try container.decodeIfPresent(Int.self, forKey: .runDow)
        runDom = try container.decodeIfPresent(Int.self, forKey: .runDom)
        lastRunAt = try container.decodeIfPresent(Date.self, forKey: .lastRunAt)
        nextRunAt = try container.decodeIfPresent(Date.self, forKey: .nextRunAt)
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt)
        rounds = try container.decodeIfPresent(Int.self, forKey: .rounds) ?? 3
        sourcesPerRound = try container.decodeIfPresent(Int.self, forKey: .sourcesPerRound) ?? 10
        trustedSources = try container.decodeIfPresent([String].self, forKey: .trustedSources) ?? []
        blockedSources = try container.decodeIfPresent([String].self, forKey: .blockedSources) ?? []
        researchDepth = try container.decodeIfPresent(String.self, forKey: .researchDepth) ?? "standard"
        alpacaTradingEnabled = try container.decodeIfPresent(Bool.self, forKey: .alpacaTradingEnabled) ?? false
        sourceTypes = try container.decodeIfPresent([String].self, forKey: .sourceTypes) ?? []
        timelimit = try container.decodeIfPresent(String.self, forKey: .timelimit) ?? "m"
    }
}

public struct PeriodicResearchRequest: Encodable, Sendable {
    public var topic: String
    public var rounds: Int
    public var sourcesPerRound: Int
    public var trustedSources: [String]
    public var blockedSources: [String]
    public var researchDepth: String
    public var sourceTypes: [String]
    public var timelimit: String
    public var alpacaTradingEnabled: Bool
    public var periodicInterval: String
    public var periodicHour: Int?
    public var periodicDow: Int?
    public var periodicDom: Int?

    public init(
        topic: String,
        rounds: Int = 3,
        sourcesPerRound: Int = 10,
        trustedSources: [String] = [],
        blockedSources: [String] = [],
        researchDepth: String = "standard",
        sourceTypes: [String] = [],
        timelimit: String = "m",
        alpacaTradingEnabled: Bool = false,
        periodicInterval: String = "daily",
        periodicHour: Int? = nil,
        periodicDow: Int? = nil,
        periodicDom: Int? = nil
    ) {
        self.topic = topic
        self.rounds = rounds
        self.sourcesPerRound = sourcesPerRound
        self.trustedSources = trustedSources
        self.blockedSources = blockedSources
        self.researchDepth = researchDepth
        self.sourceTypes = sourceTypes
        self.timelimit = timelimit
        self.alpacaTradingEnabled = alpacaTradingEnabled
        self.periodicInterval = periodicInterval
        self.periodicHour = periodicHour
        self.periodicDow = periodicDow
        self.periodicDom = periodicDom
    }

    enum CodingKeys: String, CodingKey {
        case topic
        case rounds
        case sourcesPerRound = "sources_per_round"
        case autoMode = "auto_mode"
        case trustedSources = "trusted_sources"
        case blockedSources = "blocked_sources"
        case researchDepth = "research_depth"
        case sourceTypes = "source_types"
        case timelimit
        case alpacaTradingEnabled = "alpaca_trading_enabled"
        case periodicInterval = "periodic_interval"
        case periodicHour = "periodic_hour"
        case periodicDow = "periodic_dow"
        case periodicDom = "periodic_dom"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(topic, forKey: .topic)
        try container.encode(rounds, forKey: .rounds)
        try container.encode(sourcesPerRound, forKey: .sourcesPerRound)
        try container.encode(true, forKey: .autoMode)
        try container.encode(trustedSources, forKey: .trustedSources)
        try container.encode(blockedSources, forKey: .blockedSources)
        try container.encode(researchDepth, forKey: .researchDepth)
        try container.encode(sourceTypes, forKey: .sourceTypes)
        try container.encode(timelimit == "all" ? "" : timelimit, forKey: .timelimit)
        try container.encode(alpacaTradingEnabled, forKey: .alpacaTradingEnabled)
        try container.encode(periodicInterval, forKey: .periodicInterval)
        try container.encodeIfPresent(periodicHour, forKey: .periodicHour)
        try container.encodeIfPresent(periodicDow, forKey: .periodicDow)
        try container.encodeIfPresent(periodicDom, forKey: .periodicDom)
    }
}

public struct PeriodicResearchListResponse: Decodable, Sendable {
    public let configs: [PeriodicResearchSummary]
}

public struct PeriodicCreateResponse: Decodable, Sendable {
    public let id: String
    public let nextRunAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case nextRunAt = "next_run_at"
    }
}

public struct PeriodicToggleRequest: Encodable, Sendable {
    public let enabled: Bool
}

public struct PeriodicToggleResponse: Decodable, Sendable {
    public let enabled: Bool
}
