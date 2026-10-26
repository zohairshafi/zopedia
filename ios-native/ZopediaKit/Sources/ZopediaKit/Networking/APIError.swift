import Foundation

public enum APIError: Error, Sendable, Equatable {
    case invalidURL
    case transport(String)
    case http(status: Int, detail: String)
    case unauthorized
    case passwordChangeRequired
    case conflict(String)
    case decoding(String)
    case cancelled
    case streamLost
    case server(String)
}

/// Pull a human-readable message out of FastAPI's error bodies.
public enum HTTPErrorDetail {
    public static func from(_ data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] else {
            return nil
        }
        if let text = detail as? String { return text }
        if let items = detail as? [[String: Any]] {
            let messages = items.compactMap { $0["msg"] as? String }
            return messages.isEmpty ? nil : messages.joined(separator: "; ")
        }
        return nil
    }
}

extension APIError: LocalizedError {
    public var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "The server URL is not valid."
        case .transport(let message):
            return message
        case .http(_, let detail):
            return detail
        case .unauthorized:
            return "Your session has expired. Sign in again."
        case .passwordChangeRequired:
            return "You must change your password before continuing."
        case .conflict(let detail):
            return detail
        case .decoding(let message):
            return "Could not read the server response. \(message)"
        case .cancelled:
            return nil
        case .streamLost:
            return "The connection was lost."
        case .server(let message):
            return message
        }
    }
}
