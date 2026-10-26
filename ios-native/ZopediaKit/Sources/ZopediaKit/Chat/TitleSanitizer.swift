import Foundation

public enum TitleSanitizer {
    /// The title model occasionally returns a whole sentence, a Markdown heading,
    /// or a literal "Title:" prefix. Normalize it into something a list row can show.
    public static func clean(_ raw: String, fallback: String) -> String {
        var title = raw.trimmingCharacters(in: .whitespacesAndNewlines)

        if title.lowercased().hasPrefix("title:") {
            title = String(title.dropFirst("title:".count))
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }

        title = title.trimmingCharacters(in: CharacterSet(charactersIn: "#*_`\"' "))
        title = title.replacingOccurrences(of: "\n", with: " ")

        if title.count > 100 {
            title = String(title.prefix(100)).trimmingCharacters(in: .whitespaces)
        }

        let words = title.split(separator: " ")
        if words.count > 12 {
            title = words.prefix(12).joined(separator: " ")
        }

        return title.isEmpty ? fallback : title
    }

    public static func fallback(from text: String) -> String {
        let firstLine = text.split(separator: "\n", maxSplits: 1).first.map(String.init) ?? text
        let trimmed = firstLine.trimmingCharacters(in: .whitespacesAndNewlines)
        let shortened = String(trimmed.prefix(48))
        return shortened.isEmpty ? "New Chat" : shortened
    }
}
