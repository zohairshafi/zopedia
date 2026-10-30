import Foundation
import Observation

/// Per-app chat tuning. Defaults reproduce the pre-update request exactly:
/// web search on, no thinking fields, all other optional tools off.
@MainActor
@Observable
final class ChatOptionsStore {
    enum Thinking: Equatable {
        case serverDefault
        case off
        case on
        case effort(String)

        var label: String {
            switch self {
            case .serverDefault: return "Default"
            case .off: return "Off"
            case .on: return "On"
            case .effort(let level): return level.capitalized
            }
        }

        var isActive: Bool {
            self != .serverDefault
        }
    }

    var thinking: Thinking {
        didSet { defaults.set(Self.code(for: thinking), forKey: Keys.thinking) }
    }
    var webSearch: Bool {
        didSet { defaults.set(webSearch, forKey: Keys.webSearch) }
    }
    var database: Bool {
        didSet { defaults.set(database, forKey: Keys.database) }
    }
    var alpacaData: Bool {
        didSet { defaults.set(alpacaData, forKey: Keys.alpacaData) }
    }
    var alpacaTrade: Bool {
        didSet { defaults.set(alpacaTrade, forKey: Keys.alpacaTrade) }
    }
    /// Threads the user has explicitly chosen to log on the server.
    var loggedThreadIDs: Set<String> {
        didSet { defaults.set(Array(loggedThreadIDs), forKey: Keys.loggedThreads) }
    }

    @ObservationIgnored private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        thinking = Self.thinking(from: defaults.string(forKey: Keys.thinking))
        webSearch = defaults.object(forKey: Keys.webSearch) as? Bool ?? true
        database = defaults.bool(forKey: Keys.database)
        alpacaData = defaults.bool(forKey: Keys.alpacaData)
        alpacaTrade = defaults.bool(forKey: Keys.alpacaTrade)
        loggedThreadIDs = Set(defaults.stringArray(forKey: Keys.loggedThreads) ?? [])
    }

    func isLogging(threadID: String) -> Bool {
        loggedThreadIDs.contains(threadID)
    }

    func setLogging(_ logging: Bool, threadID: String) {
        if logging {
            loggedThreadIDs.insert(threadID)
        } else {
            loggedThreadIDs.remove(threadID)
        }
    }

    var enabledTools: [String] {
        var tools = ["read_wiki_page", "search_wiki", "ask_user_question"]
        if webSearch { tools.append("web_search") }
        if database {
            tools.append(contentsOf: ["execute_sql_query", "describe_database_schema"])
        }
        if alpacaData {
            tools.append(contentsOf: ["alpaca_market_data", "alpaca_news", "alpaca_account"])
        }
        if alpacaTrade { tools.append("alpaca_trade") }
        return tools
    }

    var reasoningEffort: String? {
        if case .effort(let level) = thinking { return level }
        return nil
    }

    var enableThinking: Bool? {
        switch thinking {
        case .off: return false
        case .on: return true
        default: return nil
        }
    }

    private enum Keys {
        static let thinking = "zopedia.chat.thinking"
        static let webSearch = "zopedia.chat.webSearch"
        static let database = "zopedia.chat.database"
        static let alpacaData = "zopedia.chat.alpacaData"
        static let alpacaTrade = "zopedia.chat.alpacaTrade"
        static let loggedThreads = "zopedia.chat.loggedThreads"
    }

    private static func code(for thinking: Thinking) -> String {
        switch thinking {
        case .serverDefault: return "default"
        case .off: return "off"
        case .on: return "on"
        case .effort(let level): return "effort:\(level)"
        }
    }

    private static func thinking(from code: String?) -> Thinking {
        guard let code else { return .serverDefault }
        switch code {
        case "off": return .off
        case "on": return .on
        case "effort:low": return .effort("low")
        case "effort:medium": return .effort("medium")
        case "effort:high": return .effort("high")
        case "effort:max": return .effort("max")
        default: return .serverDefault
        }
    }
}
