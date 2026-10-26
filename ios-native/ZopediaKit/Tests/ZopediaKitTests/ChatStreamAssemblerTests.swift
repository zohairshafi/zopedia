import XCTest
@testable import ZopediaKit

final class ChatStreamAssemblerTests: XCTestCase {
    func testTextAndReasoningAccumulate() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.reasoningDelta("think "))
        assembler.apply(.reasoningDelta("more"))
        assembler.apply(.textDelta("Hello "))
        assembler.apply(.textDelta("world"))

        XCTAssertEqual(assembler.reasoning, "think more")
        XCTAssertEqual(assembler.text, "Hello world")
        XCTAssertTrue(assembler.hasContent)
    }

    func testToolStartAndEndAreMatched() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.toolStart(ToolStart(
            name: "search_wiki",
            callID: "c1",
            arguments: .object(["q": .string("oil")])
        )))
        assembler.apply(.toolEnd(ToolEnd(
            name: "search_wiki",
            callID: "c1",
            result: #"{"hits":2}"#
        )))

        XCTAssertEqual(assembler.tools.count, 1)
        XCTAssertEqual(assembler.tools[0].toolName, "search_wiki")
        XCTAssertEqual(assembler.tools[0].result, #"{"hits":2}"#)
    }

    func testToolEndWithoutStartStillCreatesAPart() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.toolEnd(ToolEnd(name: "x", callID: "c1", result: "ok")))

        XCTAssertEqual(assembler.tools.count, 1)
        XCTAssertEqual(assembler.tools[0].result, "ok")
    }

    func testTextOnlyMessageUsesPlainTextContent() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.textDelta("answer"))

        let message = assembler.message(id: "m1", parentID: "u1", createdAt: Date())

        XCTAssertEqual(message.content, .text("answer"))
        XCTAssertEqual(message.visibleText, "answer")
        XCTAssertNil(message.reasoningContent)
    }

    func testMessageKeepsReasoningAndToolParts() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.reasoningDelta("why"))
        assembler.apply(.toolStart(ToolStart(name: "t", callID: "c1", arguments: .null)))
        assembler.apply(.toolEnd(ToolEnd(name: "t", callID: "c1", result: "r")))
        assembler.apply(.textDelta("answer"))

        let message = assembler.message(id: "m1", parentID: nil, createdAt: Date())

        XCTAssertEqual(message.reasoningContent, "why")
        guard case .parts(let parts) = message.content else {
            return XCTFail("expected parts")
        }
        XCTAssertEqual(parts.count, 3)
        XCTAssertEqual(message.visibleText, "answer")
    }

    func testErrorAndDoneFlags() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.error("boom"))
        assembler.apply(.done)

        XCTAssertEqual(assembler.errorMessage, "boom")
        XCTAssertTrue(assembler.isDone)
    }

    func testEmptyAssemblerHasNoContent() {
        let assembler = ChatStreamAssembler()
        XCTAssertFalse(assembler.hasContent)
    }
}
