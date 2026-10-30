import Foundation
import XCTest
@testable import ZopediaKit

final class LaTeXPreprocessorTests: XCTestCase {
    private struct MathImage: Equatable {
        let kind: String
        let latex: String
    }

    func testInlineParenthesesAreRendered() {
        let output = LaTeXPreprocessor.preprocess("Euler: \\(e^{i\\pi}+1=0\\)")
        XCTAssertEqual(
            mathImages(in: output),
            [MathImage(kind: "inline", latex: "e^{i\\pi}+1=0")]
        )
        XCTAssertTrue(output.hasPrefix("Euler: ![Math]("))
    }

    func testDisplayBracketsBecomeABlock() {
        let output = LaTeXPreprocessor.preprocess("Before\n\\[\\frac{a}{b}\\]\nAfter")
        XCTAssertEqual(
            mathImages(in: output),
            [MathImage(kind: "display", latex: "\\frac{a}{b}")]
        )
        XCTAssertTrue(output.contains("\n\n![Math](zopedia-math://display?"))
    }

    func testDollarMathIsRendered() {
        let output = LaTeXPreprocessor.preprocess("The value is $x + y$ today.")
        XCTAssertEqual(
            mathImages(in: output),
            [MathImage(kind: "inline", latex: "x + y")]
        )
    }

    func testDisplayDollarMathIsRendered() {
        let output = LaTeXPreprocessor.preprocess("$$E = mc^2$$")
        XCTAssertEqual(
            mathImages(in: output),
            [MathImage(kind: "display", latex: "E = mc^2")]
        )
    }

    func testCurrencyIsNotMath() {
        let input = "Holdings fell from $3.2 trillion to $2.7 trillion."
        XCTAssertEqual(LaTeXPreprocessor.preprocess(input), input)
    }

    func testFencedCodeIsUntouched() {
        let input = "```\n$x + y$\n\\(z\\)\n```"
        XCTAssertEqual(LaTeXPreprocessor.preprocess(input), input)
    }

    func testInlineCodeIsUntouched() {
        let input = "Use `$x$` and `\\(y\\)` literally."
        XCTAssertEqual(LaTeXPreprocessor.preprocess(input), input)
    }

    func testEscapedDollarIsUntouched() {
        let input = "A literal \\$5 bill."
        XCTAssertEqual(LaTeXPreprocessor.preprocess(input), input)
    }

    func testBareEnvironmentBlockIsRendered() {
        let input = "[\n\\begin{matrix} a & b \\\\ c & d \\end{matrix}\n]"
        XCTAssertEqual(
            mathImages(in: LaTeXPreprocessor.preprocess(input)),
            [MathImage(kind: "display", latex: "\\begin{matrix} a & b \\\\ c & d \\end{matrix}")]
        )
    }

    func testUnclosedDollarIsUntouched() {
        let input = "It costs $5 and the formula is $x + y"
        XCTAssertEqual(LaTeXPreprocessor.preprocess(input), input)
    }

    private func mathImages(in output: String) -> [MathImage] {
        let pattern = #"!\[Math\]\((zopedia-math://[^)]+)\)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let source = output as NSString
        return regex.matches(in: output, range: NSRange(location: 0, length: source.length))
            .compactMap { match in
                guard match.numberOfRanges > 1 else { return nil }
                let raw = source.substring(with: match.range(at: 1))
                guard let url = URL(string: raw),
                      let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
                      let latex = components.queryItems?.first(where: { $0.name == "tex" })?.value else {
                    return nil
                }
                return MathImage(kind: url.host ?? "", latex: latex)
            }
    }
}
