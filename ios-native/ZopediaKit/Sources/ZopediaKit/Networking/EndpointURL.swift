import Foundation

extension URL {
    /// Append a slash-separated API path without percent-encoding the slashes.
    func zopediaURL(path: String, query: [URLQueryItem] = []) -> URL? {
        guard var components = URLComponents(url: self, resolvingAgainstBaseURL: false) else {
            return nil
        }
        let basePath = components.path
        let suffix = path.hasPrefix("/") ? path : "/" + path
        let trimmedBase = basePath.hasSuffix("/") ? String(basePath.dropLast()) : basePath
        components.path = trimmedBase + suffix
        if !query.isEmpty {
            components.queryItems = query
        }
        return components.url
    }
}
