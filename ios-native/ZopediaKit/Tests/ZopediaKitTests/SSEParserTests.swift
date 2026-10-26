import XCTest
@testable import ZopediaKit

final class SSEParserTests: XCTestCase {
    func testSingleFrame() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("data: {\"a\":1}\n\n"), ["{\"a\":1}"])
    }

    func testMultipleFramesInOneChunk() {
        var parser = SSEParser()
        XCTAssertEqual(
            parser.append("data: one\n\ndata: two\n\n"),
            ["one", "two"]
        )
    }

    func testFrameSplitAcrossChunks() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("data: {\"a\":"), [])
        XCTAssertEqual(parser.append("1}\n\n"), ["{\"a\":1}"])
    }

    func testSplitExactlyOnDelimiter() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("data: x\n"), [])
        XCTAssertEqual(parser.append("\n"), ["x"])
    }

    func testCRLFIsNormalized() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("data: x\r\n\r\n"), ["x"])
    }

    func testMultiLineDataIsJoined() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("data: line1\ndata: line2\n\n"), ["line1\nline2"])
    }

    func testCommentsAndOtherFieldsAreIgnored() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append(": ping\nevent: message\ndata: x\n\n"), ["x"])
    }

    func testEmptyEventProducesNothing() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("\n\n"), [])
    }

    func testFinishFlushesTrailingEvent() {
        var parser = SSEParser()
        XCTAssertEqual(parser.append("data: tail"), [])
        XCTAssertEqual(parser.finish(), ["tail"])
    }
}
