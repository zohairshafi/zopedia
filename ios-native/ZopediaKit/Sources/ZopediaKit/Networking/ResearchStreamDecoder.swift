import Foundation

/// Turns one research SSE payload into a typed event.
///
/// Unknown event types are returned as `.unknown` so newer server events do not
/// break an older client. A frame without a `type` is malformed and throws.
public enum ResearchStreamDecoder {
    public static func decode(_ payload: String) throws -> ResearchEvent {
        if payload == "[DONE]" { return .done }

        guard let data = payload.data(using: .utf8) else {
            throw APIError.decoding("Research frame is not UTF-8")
        }
        let json: Any
        do {
            json = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw APIError.decoding("Malformed research stream frame")
        }
        guard let object = json as? [String: Any] else {
            throw APIError.decoding("Research stream frame is not an object")
        }
        guard let type = object["type"] as? String else {
            throw APIError.decoding("Research stream frame has no type")
        }

        switch type {
        case "research_started":
            return .started(
                topic: string(object, "topic"),
                totalRounds: integer(object, "total_rounds"),
                sourcesPerRound: integer(object, "sources_per_round"),
                autoMode: boolean(object, "auto_mode")
            )
        case "research_survey":
            return .survey(string(object, "content"))
        case "research_round_start":
            return .roundStarted(
                round: integer(object, "round"),
                totalRounds: integer(object, "total_rounds")
            )
        case "research_searching":
            return .searching(
                round: integer(object, "round"),
                queries: strings(object["queries"])
            )
        case "research_sources_found":
            return .sourcesFound(
                round: integer(object, "round"),
                sources: try decodeSources(object["sources"])
            )
        case "research_awaiting_approval":
            return .awaitingApproval(
                round: integer(object, "round"),
                sourceCount: integer(object, "source_count")
            )
        case "research_ingest_start":
            return .ingestStart(url: string(object, "url"))
        case "research_ingest_complete":
            let error = string(object, "error")
            return .ingestComplete(
                url: string(object, "url"),
                title: string(object, "title"),
                status: string(object, "status"),
                error: error.isEmpty ? nil : error
            )
        case "research_maintenance_start":
            return .maintenanceStart(step: string(object, "step"))
        case "research_maintenance_progress":
            return .maintenanceProgress(
                step: string(object, "step"),
                details: try jsonValue(object["details"])
            )
        case "research_maintenance_complete":
            let summary = object["summary"] as? [String: Any] ?? [:]
            return .maintenanceComplete(stepsCompleted: integer(summary, "steps_completed"))
        case "research_round_complete":
            return .roundComplete(
                round: integer(object, "round"),
                ingested: integer(object, "sources_ingested"),
                failed: integer(object, "sources_failed"),
                newPages: strings(object["new_pages"]),
                failedPages: strings(object["failed_pages"])
            )
        case "research_summarizing":
            return .summarizing(string(object, "message"))
        case "research_final_summary":
            return .finalSummary(string(object, "content"))
        case "research_warnings":
            return .warnings(try decodeWarnings(object["warnings"]))
        case "research_title":
            return .title(string(object, "title"))
        case "research_tool_status":
            let text = (object["text"] as? String) ?? (object["content"] as? String) ?? ""
            return .toolStatus(text)
        case "research_tool_start":
            return .toolStart(
                name: string(object, "tool_name"),
                callID: string(object, "tool_call_id"),
                arguments: try jsonValue(object["arguments"])
            )
        case "research_tool_end":
            return .toolEnd(
                name: string(object, "tool_name"),
                callID: string(object, "tool_call_id"),
                result: string(object, "result")
            )
        case "research_complete":
            return .completed(totalIngested: integer(object, "total_sources_ingested"))
        case "research_error":
            return .error(string(object, "message"))
        case "research_cancelled":
            return .cancelled(string(object, "message"))
        default:
            return .unknown(type: type)
        }
    }

    private static func string(_ object: [String: Any], _ key: String) -> String {
        object[key] as? String ?? ""
    }

    private static func integer(_ object: [String: Any], _ key: String) -> Int {
        if let value = object[key] as? Int { return value }
        if let value = object[key] as? Double { return Int(value) }
        if let value = object[key] as? String, let parsed = Int(value) { return parsed }
        return 0
    }

    private static func boolean(_ object: [String: Any], _ key: String) -> Bool {
        if let value = object[key] as? Bool { return value }
        if let value = object[key] as? Int { return value != 0 }
        return false
    }

    private static func strings(_ value: Any?) -> [String] {
        (value as? [String]) ?? (value as? [Any])?.compactMap { $0 as? String } ?? []
    }

    private static func jsonValue(_ value: Any?) throws -> JSONValue {
        try JSONValue(any: value ?? [String: Any]())
    }

    private static func decodeSources(_ value: Any?) throws -> [ResearchSource] {
        guard let array = value as? [[String: Any]] else { return [] }
        let data = try JSONSerialization.data(withJSONObject: array)
        return try JSONDecoder().decode([ResearchSource].self, from: data)
    }

    private static func decodeWarnings(_ value: Any?) throws -> [ResearchWarning] {
        guard let array = value as? [[String: Any]] else { return [] }
        let data = try JSONSerialization.data(withJSONObject: array)
        return try JSONDecoder().decode([ResearchWarning].self, from: data)
    }
}
