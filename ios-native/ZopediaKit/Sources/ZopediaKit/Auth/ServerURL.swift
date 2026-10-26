import Foundation

public enum ServerURL {
    /// Normalize user input and reject URLs the app cannot reach.
    ///
    /// ATS blocks cleartext HTTP to public hostnames, so those must be HTTPS.
    /// Raw IPs, unqualified hostnames, and `.local` names are ATS-exempt and may
    /// use HTTP (the server itself is often a LAN box with no certificate).
    public static func normalize(_ raw: String) throws -> URL {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while text.hasSuffix("/") { text.removeLast() }

        guard let url = URL(string: text),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = url.host,
              !host.isEmpty else {
            throw APIError.invalidURL
        }

        if scheme == "http" && !isLocal(host) {
            throw APIError.http(
                status: 0,
                detail: "Use https:// for a public hostname. Plain http:// is only allowed for local addresses (IP, .local, or a single hostname)."
            )
        }
        return url
    }

    public static func isLocal(_ host: String) -> Bool {
        let lowered = host.lowercased()
        if lowered == "localhost" { return true }
        if lowered.hasSuffix(".local") { return true }
        if lowered.contains(":") { return true } // IPv6 literal
        if !lowered.contains(".") { return true } // unqualified hostname

        let parts = lowered.split(separator: ".")
        if parts.count == 4, parts.allSatisfy({ UInt8($0) != nil }) {
            return true // IPv4
        }
        return false
    }
}
