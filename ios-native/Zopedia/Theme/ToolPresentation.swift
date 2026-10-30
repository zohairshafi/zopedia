import Foundation

/// Web-parity labels and SF Symbols for tool calls.
struct ToolAppearance: Equatable {
    let title: String
    let icon: String
}

enum ToolPresentation {
    static func appearance(for name: String) -> ToolAppearance {
        switch name {
        case "read_wiki_page":
            return ToolAppearance(title: "Read wiki page", icon: "book")
        case "search_wiki":
            return ToolAppearance(title: "Search wiki", icon: "magnifyingglass")
        case "web_search":
            return ToolAppearance(title: "Web search", icon: "globe")
        case "python":
            return ToolAppearance(title: "Python", icon: "chevron.left.forwardslash.chevron.right")
        case "terminal":
            return ToolAppearance(title: "Terminal", icon: "terminal")
        case "execute_sql_query":
            return ToolAppearance(title: "SQL query", icon: "cylinder")
        case "describe_database_schema":
            return ToolAppearance(title: "Database schema", icon: "cylinder.split.1x2")
        case "ask_user_question":
            return ToolAppearance(title: "Question", icon: "questionmark.circle")
        case "alpaca_market_data":
            return ToolAppearance(title: "Market data", icon: "chart.line.uptrend.xyaxis")
        case "alpaca_news":
            return ToolAppearance(title: "Market news", icon: "newspaper")
        case "alpaca_account":
            return ToolAppearance(title: "Account", icon: "person.text.rectangle")
        case "alpaca_trade":
            return ToolAppearance(title: "Trade approval", icon: "arrow.left.arrow.right")
        default:
            return ToolAppearance(title: name, icon: "wrench.and.screwdriver")
        }
    }

    /// A tool result is treated as failed when it is JSON with a non-empty
    /// `error` field. Plain-text results are shown as completed.
    static func resultFailed(_ result: String?) -> Bool {
        guard let result,
              let data = result.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return false
        }
        if let error = object["error"] as? String {
            return !error.isEmpty
        }
        return false
    }
}
