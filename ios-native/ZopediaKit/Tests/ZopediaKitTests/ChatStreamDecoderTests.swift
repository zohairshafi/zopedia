import XCTest
@testable import ZopediaKit

final class ChatStreamDecoderTests: XCTestCase {
    func testTextDelta() throws {
        let payload = #"{"choices":[{"index":0,"delta":{"content":"hello"},"finish_reason":null}]}"#
        XCTAssertEqual(try ChatStreamDecoder.decode(payload), .textDelta("hello"))
    }

    func testReasoningDelta() throws {
        let payload = #"{"choices":[{"index":0,"delta":{"reasoning_content":"think"},"finish_reason":null}]}"#
        XCTAssertEqual(try ChatStreamDecoder.decode(payload), .reasoningDelta("think"))
    }

    func testToolStatus() throws {
        let payload = #"{"type":"tool_status","content":"Thinking..."}"#
        XCTAssertEqual(try ChatStreamDecoder.decode(payload), .toolStatus("Thinking..."))
    }

    func testToolStart() throws {
        let payload = #"{"type":"tool_start","tool_name":"ask_user_question","tool_call_id":"c1","arguments":{"question":"Pick","options":["a","b"]}}"#
        guard case .toolStart(let start) = try ChatStreamDecoder.decode(payload) else {
            return XCTFail("expected toolStart")
        }
        XCTAssertEqual(start.name, "ask_user_question")
        XCTAssertEqual(start.callID, "c1")
        XCTAssertEqual(start.arguments.objectValue?["options"]?.arrayValue?.count, 2)
    }

    func testToolEnd() throws {
        let payload = #"{"type":"tool_end","tool_name":"search_wiki","tool_call_id":"c1","result":"{\"ok\":true}"}"#
        XCTAssertEqual(
            try ChatStreamDecoder.decode(payload),
            .toolEnd(ToolEnd(name: "search_wiki", callID: "c1", result: #"{"ok":true}"#))
        )
    }

    func testUsage() throws {
        let payload = #"{"choices":[],"usage":{"total_tokens":3}}"#
        guard case .usage(let value) = try ChatStreamDecoder.decode(payload) else {
            return XCTFail("expected usage")
        }
        XCTAssertEqual(value.objectValue?["total_tokens"]?.intValue, 3)
    }

    func testErrorAsString() throws {
        XCTAssertEqual(
            try ChatStreamDecoder.decode(#"{"error":"boom"}"#),
            .error("boom")
        )
    }

    func testErrorAsObject() throws {
        XCTAssertEqual(
            try ChatStreamDecoder.decode(#"{"error":{"message":"boom"}}"#),
            .error("boom")
        )
    }

    func testDone() throws {
        XCTAssertEqual(try ChatStreamDecoder.decode("[DONE]"), .done)
    }

    func testMalformedFrameThrows() {
        XCTAssertThrowsError(try ChatStreamDecoder.decode("not json"))
    }

    func testUnknownTypeIsIgnored() throws {
        XCTAssertNil(try ChatStreamDecoder.decode(#"{"type":"something_new"}"#))
    }
}
