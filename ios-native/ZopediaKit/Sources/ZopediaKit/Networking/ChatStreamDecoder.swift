import Foundation

/// Turns one SSE payload into a typed chat event.
///
/// The server interleaves three shapes: custom `type` events (tool activity),
/// OpenAI `chat.completion.chunk` objects, and a bare `{ "error": ... }` object.
public enum ChatStreamDecoder {
    public static func decode(_ payload: String) throws -> ChatStreamEvent? {
        if payload == "[DONE]" { return .done }

        guard let data = payload.data(using: .utf8) else {
            throw APIError.decoding("Stream frame is not UTF-8")
        }
        let json: Any
        do {
            json = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw APIError.decoding("Malformed stream frame")
        }
        guard let object = json as? [String: Any] else {
            throw APIError.decoding("Stream frame is not an object")
        }

        if let type = object["type"] as? String {
            switch type {
            case "tool_status":
                return .toolStatus(object["content"] as? String ?? "")
            case "tool_start":
                guard let name = object["tool_name"] as? String,
                      let callID = object["tool_call_id"] as? String else {
                    throw APIError.decoding("tool_start missing name or id")
                }
                let arguments: JSONValue
                do {
                    arguments = try JSONValue(any: object["arguments"] ?? [String: Any]())
                } catch {
                    throw APIError.decoding("tool_start arguments are not JSON")
                }
                return .toolStart(ToolStart(name: name, callID: callID, arguments: arguments))
            case "tool_end":
                guard let name = object["tool_name"] as? String,
                      let callID = object["tool_call_id"] as? String else {
                    throw APIError.decoding("tool_end missing name or id")
                }
                return .toolEnd(
                    ToolEnd(name: name, callID: callID, result: object["result"] as? String ?? "")
                )
            default:
                return nil
            }
        }

        if let error = object["error"] {
            if let text = error as? String { return .error(text) }
            if let dict = error as? [String: Any], let message = dict["message"] as? String {
                return .error(message)
            }
            return .error("Unknown stream error")
        }

        if let choices = object["choices"] as? [[String: Any]],
           let delta = choices.first?["delta"] as? [String: Any] {
            if let reasoning = delta["reasoning_content"] as? String, !reasoning.isEmpty {
                return .reasoningDelta(reasoning)
            }
            if let content = delta["content"] as? String, !content.isEmpty {
                return .textDelta(content)
            }
        }

        if let usage = object["usage"] {
            return .usage(try JSONValue(any: usage))
        }

        return nil
    }
}
