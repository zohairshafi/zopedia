import Foundation

/// Body for `POST /api/research/stream`.
public struct ResearchConfig: Encodable, Sendable {
    public var topic: String
    public var rounds: Int
    public var sourcesPerRound: Int
    public var autoMode: Bool
    public var trustedSources: [String]
    public var blockedSources: [String]
    public var researchDepth: String
    public var sourceTypes: [String]
    /// "all", "d", "w", "m", or "y". The server maps "all" to no limit.
    public var timelimit: String
    public var alpacaTradingEnabled: Bool
    public var sessionID: String?

    public init(
        topic: String,
        rounds: Int = 3,
        sourcesPerRound: Int = 10,
        autoMode: Bool = false,
        trustedSources: [String] = [],
        blockedSources: [String] = [],
        researchDepth: String = "standard",
        sourceTypes: [String] = [],
        timelimit: String = "m",
        alpacaTradingEnabled: Bool = false,
        sessionID: String? = nil
    ) {
        self.topic = topic
        self.rounds = rounds
        self.sourcesPerRound = sourcesPerRound
        self.autoMode = autoMode
        self.trustedSources = trustedSources
        self.blockedSources = blockedSources
        self.researchDepth = researchDepth
        self.sourceTypes = sourceTypes
        self.timelimit = timelimit
        self.alpacaTradingEnabled = alpacaTradingEnabled
        self.sessionID = sessionID
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
        case sessionID = "session_id"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(topic, forKey: .topic)
        try container.encode(rounds, forKey: .rounds)
        try container.encode(sourcesPerRound, forKey: .sourcesPerRound)
        try container.encode(autoMode, forKey: .autoMode)
        try container.encode(trustedSources, forKey: .trustedSources)
        try container.encode(blockedSources, forKey: .blockedSources)
        try container.encode(researchDepth, forKey: .researchDepth)
        try container.encode(sourceTypes, forKey: .sourceTypes)
        try container.encode(timelimit == "all" ? "" : timelimit, forKey: .timelimit)
        try container.encode(alpacaTradingEnabled, forKey: .alpacaTradingEnabled)
        try container.encodeIfPresent(sessionID, forKey: .sessionID)
    }
}

public struct ResearchSource: Decodable, Hashable, Identifiable, Sendable {
    public let url: String
    public let title: String
    public let snippet: String
    public let sourceType: String
    public let isTrusted: Bool
    public let relevance: Double?
    public let alreadyInWiki: Bool

    public var id: String { url }

    enum CodingKeys: String, CodingKey {
        case url
        case title
        case snippet
        case sourceType = "source_type"
        case isTrusted = "is_trusted"
        case relevance
        case alreadyInWiki = "already_in_wiki"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        url = try container.decodeIfPresent(String.self, forKey: .url) ?? ""
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? ""
        snippet = try container.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        sourceType = try container.decodeIfPresent(String.self, forKey: .sourceType) ?? ""
        isTrusted = try container.decodeIfPresent(Bool.self, forKey: .isTrusted) ?? false
        relevance = try? container.decodeIfPresent(Double.self, forKey: .relevance)
        alreadyInWiki = try container.decodeIfPresent(Bool.self, forKey: .alreadyInWiki) ?? false
    }
}

public struct ResearchWarning: Decodable, Hashable, Sendable {
    public let url: String
    public let error: String

    enum CodingKeys: String, CodingKey {
        case url
        case error
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        url = try container.decodeIfPresent(String.self, forKey: .url) ?? ""
        error = try container.decodeIfPresent(String.self, forKey: .error) ?? ""
    }
}

public enum ResearchEvent: Equatable, Sendable {
    case started(topic: String, totalRounds: Int, sourcesPerRound: Int, autoMode: Bool)
    case survey(String)
    case roundStarted(round: Int, totalRounds: Int)
    case searching(round: Int, queries: [String])
    case sourcesFound(round: Int, sources: [ResearchSource])
    case awaitingApproval(round: Int, sourceCount: Int)
    case ingestStart(url: String)
    case ingestComplete(url: String, title: String, status: String, error: String?)
    case maintenanceStart(step: String)
    case maintenanceProgress(step: String, details: JSONValue)
    case maintenanceComplete(stepsCompleted: Int)
    case roundComplete(round: Int, ingested: Int, failed: Int, newPages: [String], failedPages: [String])
    case summarizing(String)
    case finalSummary(String)
    case warnings([ResearchWarning])
    case title(String)
    case toolStatus(String)
    case toolStart(name: String, callID: String, arguments: JSONValue)
    case toolEnd(name: String, callID: String, result: String)
    case completed(totalIngested: Int)
    case error(String)
    case cancelled(String)
    case done
    case unknown(type: String)
}
