import Foundation

/// Convert LaTeX math in Markdown into inline images the app can render.
///
/// The web client normalises `\(...\)`/`\[...\]` and lets remark-math parse
/// `$...$`/`$$...$$`. MarkdownUI has no math support, so this scanner performs
/// the same normalization and replaces each math span with a `zopedia-math`
/// image. It walks the text instead of using regular expressions so code
/// spans, fenced blocks and escaped dollar signs are never rewritten.
public enum LaTeXPreprocessor {
    public static func preprocess(_ text: String) -> String {
        let characters = Array(text)
        var output = ""
        var index = 0
        var lineStart = true

        while index < characters.count {
            let character = characters[index]

            if character == "\n" {
                output.append(character)
                index += 1
                lineStart = true
                continue
            }

            if lineStart, let fence = fence(at: index, in: characters) {
                let end = endOfFence(fence, from: fence.end, in: characters)
                output.append(contentsOf: characters[index..<end])
                index = end
                lineStart = output.last == "\n"
                continue
            }

            if character == " " || character == "\t" {
                output.append(character)
                index += 1
                continue
            }
            lineStart = false

            if character == "`" {
                let run = runLength(of: "`", at: index, in: characters)
                if let close = closingRun(of: "`", length: run, from: index + run, in: characters) {
                    output.append(contentsOf: characters[index..<close])
                    index = close
                } else {
                    output.append(contentsOf: characters[index..<index + run])
                    index += run
                }
                continue
            }

            if character == "\\" {
                if index + 1 < characters.count, characters[index + 1] == "$" {
                    output.append("\\$")
                    index += 2
                    continue
                }
                if index + 1 < characters.count, characters[index + 1] == "(",
                   let close = range(of: "\\)", from: index + 2, in: characters),
                   !containsNewline(characters, from: index + 2, to: close) {
                    appendMath(
                        String(characters[(index + 2)..<close]),
                        display: false,
                        to: &output
                    )
                    index = close + 2
                    continue
                }
                if index + 1 < characters.count, characters[index + 1] == "[",
                   let close = range(of: "\\]", from: index + 2, in: characters) {
                    appendMath(
                        String(characters[(index + 2)..<close]),
                        display: true,
                        to: &output
                    )
                    index = close + 2
                    continue
                }
                output.append(character)
                index += 1
                continue
            }

            if character == "$", index + 1 < characters.count {
                if characters[index + 1] == "$" {
                    if let close = range(of: "$$", from: index + 2, in: characters) {
                        appendMath(
                            String(characters[(index + 2)..<close]),
                            display: true,
                            to: &output
                        )
                        index = close + 2
                        continue
                    }
                } else if isInlineMathOpening(characters, at: index),
                          let close = inlineMathClose(from: index + 1, in: characters) {
                    appendMath(
                        String(characters[(index + 1)..<close]),
                        display: false,
                        to: &output
                    )
                    index = close + 1
                    continue
                }
            }

            if character == "[", let env = bareEnvironment(at: index, in: characters) {
                appendMath(env.math, display: true, to: &output)
                index = env.end
                continue
            }

            output.append(character)
            index += 1
        }

        return output
    }

    // MARK: - Math replacement

    private static func appendMath(_ latex: String, display: Bool, to output: inout String) {
        let trimmed = latex.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            output.append(display ? "$$$$" : "$$")
            return
        }

        let kind = display ? "display" : "inline"
        let url = "zopedia-math://\(kind)?tex=\(encode(trimmed))"
        if display {
            output.append("\n\n![Math](\(url))\n\n")
        } else {
            output.append("![Math](\(url))")
        }
    }

    private static func encode(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    // MARK: - Code

    private struct Fence {
        let character: Character
        let count: Int
        let end: Int
    }

    private static func fence(at index: Int, in characters: [Character]) -> Fence? {
        let character = characters[index]
        guard character == "`" || character == "~" else { return nil }
        let count = runLength(of: character, at: index, in: characters)
        guard count >= 3 else { return nil }

        var end = index + count
        while end < characters.count, characters[end] != "\n" {
            end += 1
        }
        return Fence(character: character, count: count, end: end)
    }

    private static func endOfFence(_ fence: Fence, from start: Int, in characters: [Character]) -> Int {
        var index = start
        while index < characters.count {
            if index == 0 || characters[index - 1] == "\n" {
                let count = runLength(of: fence.character, at: index, in: characters)
                if count >= fence.count {
                    var end = index + count
                    while end < characters.count, characters[end] != "\n" {
                        end += 1
                    }
                    return min(end + 1, characters.count)
                }
            }
            index += 1
        }
        return characters.count
    }

    private static func runLength(of character: Character, at index: Int, in characters: [Character]) -> Int {
        var length = 0
        var cursor = index
        while cursor < characters.count, characters[cursor] == character {
            length += 1
            cursor += 1
        }
        return length
    }

    private static func closingRun(
        of character: Character,
        length: Int,
        from start: Int,
        in characters: [Character]
    ) -> Int? {
        var index = start
        while index < characters.count {
            if characters[index] == character {
                let run = runLength(of: character, at: index, in: characters)
                if run == length {
                    return index + run
                }
                index += run
                continue
            }
            if characters[index] == "\n", length == 1 {
                // A single-backtick code span cannot cross a blank line.
                let next = index + 1
                if next < characters.count, characters[next] == "\n" {
                    return nil
                }
            }
            index += 1
        }
        return nil
    }

    // MARK: - Delimiters

    private static func range(
        of needle: String,
        from start: Int,
        in characters: [Character]
    ) -> Int? {
        let target = Array(needle)
        guard !target.isEmpty, start <= characters.count - target.count else { return nil }
        var index = start
        while index <= characters.count - target.count {
            var matched = true
            for offset in 0..<target.count where characters[index + offset] != target[offset] {
                matched = false
                break
            }
            if matched { return index }
            if characters[index] == "\\" {
                // Skip an escaped character so "\$" cannot close math.
                index += 2
                continue
            }
            index += 1
        }
        return nil
    }

    private static func containsNewline(_ characters: [Character], from start: Int, to end: Int) -> Bool {
        var index = start
        while index < end {
            if characters[index] == "\n" { return true }
            index += 1
        }
        return false
    }

    private static func isInlineMathOpening(_ characters: [Character], at index: Int) -> Bool {
        guard index + 1 < characters.count else { return false }
        let next = characters[index + 1]
        if next.isWhitespace || next == "$" || next.isNumber { return false }
        return true
    }

    private static func inlineMathClose(from start: Int, in characters: [Character]) -> Int? {
        var index = start
        while index < characters.count {
            let character = characters[index]
            if character == "\n" { return nil }
            if character == "\\" {
                index += 2
                continue
            }
            if character == "$" {
                let previous = characters[index - 1]
                let next = index + 1 < characters.count ? characters[index + 1] : " "
                if !previous.isWhitespace, !next.isNumber {
                    return index
                }
            }
            index += 1
        }
        return nil
    }

    // MARK: - Bare bracket environments

    private struct BareEnvironment {
        let math: String
        let end: Int
    }

    private static func bareEnvironment(
        at index: Int,
        in characters: [Character]
    ) -> BareEnvironment? {
        var cursor = index + 1
        while cursor < characters.count, characters[cursor].isWhitespace {
            cursor += 1
        }
        guard starts(with: "\\begin{", at: cursor, in: characters) else { return nil }

        let nameStart = cursor + "\\begin{".count
        guard let nameEnd = range(of: "}", from: nameStart, in: characters) else { return nil }
        let name = String(characters[nameStart..<nameEnd])
        guard !name.isEmpty, let end = range(of: "\\end{\(name)}", from: nameEnd + 1, in: characters) else {
            return nil
        }

        var close = end + "\\end{\(name)}".count
        while close < characters.count, characters[close].isWhitespace {
            close += 1
        }
        guard close < characters.count, characters[close] == "]" else { return nil }

        return BareEnvironment(
            math: String(characters[cursor..<end + "\\end{\(name)}".count]),
            end: close + 1
        )
    }

    private static func starts(with prefix: String, at index: Int, in characters: [Character]) -> Bool {
        let target = Array(prefix)
        guard index + target.count <= characters.count else { return false }
        for offset in 0..<target.count where characters[index + offset] != target[offset] {
            return false
        }
        return true
    }
}
