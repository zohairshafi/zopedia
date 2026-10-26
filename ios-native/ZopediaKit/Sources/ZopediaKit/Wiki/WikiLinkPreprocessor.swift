import Foundation

/// Convert wiki references into links the app can intercept.
///
/// Mirrors `frontend/src/lib/wiki-links.ts`: `[[Page]]`, plain `path/to/page.md`,
/// and `analysis/YYYY-MM-DD-HH-MM-slug` all become links to a `zopedia://wiki`
/// URL carrying the resolved vault path.
public enum WikiLinkPreprocessor {
    private static let wikiLinkPattern = #"\[\[([^\]]+)\]\]"#
    private static let pagePathPattern = #"(?<![\[\(`\/])([a-z][\w-]*\/[\w\/-]+\.md)(?![\]\)`])"#
    private static let analysisPathPattern = #"(?<![\[\(`\/])(analysis\/\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-[\w-]+)(?![\]\)`])"#

    public static func preprocess(_ text: String) -> String {
        var result = text

        result = replacing(result, pattern: wikiLinkPattern) { groups in
            let reference = groups[1]
            return "[\(reference)](\(link(for: resolvePath(reference))))"
        }

        result = replacing(result, pattern: pagePathPattern, options: [.caseInsensitive]) { groups in
            let path = groups[1]
            return "[\(path)](\(link(for: resolvePath(path))))"
        }

        result = replacing(result, pattern: analysisPathPattern, options: [.caseInsensitive]) { groups in
            let path = groups[1]
            return "[\(path)](\(link(for: path + ".md")))"
        }

        return result
    }

    public static func resolvePath(_ reference: String) -> String {
        let trimmed = reference.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.lowercased().hasSuffix(".md") {
            return trimmed
        }
        if trimmed.contains("/") || trimmed.contains(".") {
            return trimmed + ".md"
        }
        let slug = trimmed
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: "-")
            .lowercased()
        return slug + ".md"
    }

    public static func link(for path: String) -> String {
        var components = URLComponents()
        components.scheme = "zopedia"
        components.host = "wiki"
        components.queryItems = [URLQueryItem(name: "path", value: path)]
        return components.string ?? "zopedia://wiki"
    }

    public static func pagePath(from url: URL) -> String? {
        guard url.scheme == "zopedia", url.host == "wiki",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return nil
        }
        return components.queryItems?.first(where: { $0.name == "path" })?.value
    }

    /// Drop the leading YAML frontmatter block, if present.
    public static func stripFrontmatter(_ text: String) -> String {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard lines.first?.trimmingCharacters(in: .whitespaces) == "---" else {
            return text
        }
        for (index, line) in lines.enumerated().dropFirst() {
            if line.trimmingCharacters(in: .whitespaces) == "---" {
                return lines.dropFirst(index + 1).joined(separator: "\n")
            }
        }
        return text
    }

    private static func replacing(
        _ text: String,
        pattern: String,
        options: NSRegularExpression.Options = [],
        transform: ([String]) -> String?
    ) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: options) else {
            return text
        }
        let source = text as NSString
        let matches = regex.matches(
            in: text,
            range: NSRange(location: 0, length: source.length)
        )

        var result = text
        for match in matches.reversed() {
            var groups: [String] = []
            for index in 0..<match.numberOfRanges {
                let range = match.range(at: index)
                groups.append(range.location == NSNotFound ? "" : source.substring(with: range))
            }
            guard let replacement = transform(groups),
                  let range = Range(match.range, in: text) else {
                continue
            }
            result.replaceSubrange(range, with: replacement)
        }
        return result
    }
}
