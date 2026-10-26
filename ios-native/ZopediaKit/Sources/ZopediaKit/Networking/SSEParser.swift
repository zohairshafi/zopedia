import Foundation

/// Incremental Server-Sent Events parser.
///
/// Feed it arbitrary chunks (including chunks split mid-frame); it returns the
/// `data:` payload of each complete event. Blank lines delimit events.
public struct SSEParser: Sendable {
    private var buffer = ""

    public init() {}

    public mutating func append(_ chunk: String) -> [String] {
        buffer += chunk
        buffer = buffer.replacingOccurrences(of: "\r\n", with: "\n")

        var payloads: [String] = []
        while let separator = buffer.range(of: "\n\n") {
            let block = String(buffer[..<separator.lowerBound])
            buffer = String(buffer[separator.upperBound...])
            if let payload = Self.dataPayload(from: block) {
                payloads.append(payload)
            }
        }
        return payloads
    }

    /// Flush a trailing event that arrived without a terminating blank line.
    public mutating func finish() -> [String] {
        let block = buffer
        buffer = ""
        guard let payload = Self.dataPayload(from: block) else { return [] }
        return [payload]
    }

    static func dataPayload(from block: String) -> String? {
        guard !block.isEmpty else { return nil }
        var dataLines: [String] = []
        for line in block.split(separator: "\n", omittingEmptySubsequences: false) {
            guard line.hasPrefix("data:") else { continue }
            var value = line.dropFirst(5)
            if value.hasPrefix(" ") { value = value.dropFirst() }
            if value.hasSuffix("\r") { value = value.dropLast() }
            dataLines.append(String(value))
        }
        guard !dataLines.isEmpty else { return nil }
        return dataLines.joined(separator: "\n")
    }
}
