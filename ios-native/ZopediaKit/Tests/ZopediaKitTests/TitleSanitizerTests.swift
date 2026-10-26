import XCTest
@testable import ZopediaKit

final class TitleSanitizerTests: XCTestCase {
    func testStripsTitlePrefixAndMarkdown() {
        XCTAssertEqual(
            TitleSanitizer.clean("Title: ## Oil prices this week", fallback: "x"),
            "Oil prices this week"
        )
    }

    func testTruncatesToTwelveWords() {
        let raw = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
        let cleaned = TitleSanitizer.clean(raw, fallback: "x")
        XCTAssertEqual(
            cleaned,
            "one two three four five six seven eight nine ten eleven twelve"
        )
    }

    func testTruncatesLongSingleWord() {
        let raw = String(repeating: "a", count: 150)
        XCTAssertEqual(TitleSanitizer.clean(raw, fallback: "x").count, 100)
    }

    func testEmptyFallsBack() {
        XCTAssertEqual(TitleSanitizer.clean("   ", fallback: "Fallback"), "Fallback")
    }

    func testFallbackUsesFirstLineAndFortyEightCharacters() {
        let text = "A very long first line that should be shortened because it keeps going\nsecond"
        let fallback = TitleSanitizer.fallback(from: text)
        XCTAssertEqual(fallback.count, 48)
        XCTAssertFalse(fallback.contains("second"))
    }
}
