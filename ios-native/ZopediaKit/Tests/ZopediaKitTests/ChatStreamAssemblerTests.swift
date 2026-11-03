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

    func testMessageKeepsReasoningAndParts() {
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
        XCTAssertEqual(parts[0], .reasoning("why"))
        XCTAssertEqual(parts[1], .tool(ToolCallPart(
            toolCallID: "c1", toolName: "t", args: .null, result: "r"
        )))
        XCTAssertEqual(parts[2], .text("answer"))
        XCTAssertEqual(message.visibleText, "answer")
    }

    func testPartsPreserveStreamOrder() throws {
        var assembler = ChatStreamAssembler()
        assembler.apply(.textDelta("Before."))
        assembler.apply(.toolStart(ToolStart(name: "t", callID: "c1", arguments: .null)))
        assembler.apply(.toolEnd(ToolEnd(name: "t", callID: "c1", result: "r")))
        assembler.apply(.textDelta("After."))

        let message = assembler.message(id: "m1", parentID: nil, createdAt: Date())
        guard case .parts(let parts) = message.content else {
            return XCTFail("expected parts")
        }

        XCTAssertEqual(parts.count, 3)
        XCTAssertEqual(parts[0], .text("Before."))
        if case .tool(let tool) = parts[1] {
            XCTAssertEqual(tool.toolCallID, "c1")
            XCTAssertEqual(tool.result, "r")
        } else {
            XCTFail("expected the tool between the text segments")
        }
        XCTAssertEqual(parts[2], .text("After."))
        XCTAssertEqual(assembler.text, "Before.After.")
    }

    func testReasoningStaysInStreamOrder() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.textDelta("one"))
        assembler.apply(.reasoningDelta("why"))
        assembler.apply(.textDelta("two"))

        XCTAssertEqual(assembler.parts.count, 3)
        XCTAssertEqual(assembler.parts[0], .text("one"))
        XCTAssertEqual(assembler.parts[1], .reasoning("why"))
        XCTAssertEqual(assembler.parts[2], .text("two"))
        XCTAssertEqual(assembler.text, "onetwo")
        XCTAssertEqual(assembler.reasoning, "why")
    }

    func testReasoningBetweenToolCallsKeepsOrder() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.toolStart(ToolStart(name: "search_wiki", callID: "c1", arguments: .null)))
        assembler.apply(.reasoningDelta("checking"))
        assembler.apply(.toolEnd(ToolEnd(name: "search_wiki", callID: "c1", result: "ok")))
        assembler.apply(.textDelta("answer"))

        let message = assembler.message(id: "m1", parentID: nil, createdAt: Date())
        guard case .parts(let parts) = message.content else {
            return XCTFail("expected parts")
        }
        XCTAssertEqual(parts.count, 3)
        if case .tool = parts[0] {} else { XCTFail("tool first") }
        XCTAssertEqual(parts[1], .reasoning("checking"))
        XCTAssertEqual(parts[2], .text("answer"))
    }

    func testServerContentDropsReasoningParts() {
        var assembler = ChatStreamAssembler()
        assembler.apply(.reasoningDelta("why"))
        assembler.apply(.toolStart(ToolStart(name: "t", callID: "c1", arguments: .null)))
        assembler.apply(.textDelta("answer"))

        let message = assembler.message(id: "m1", parentID: nil, createdAt: Date())
        let payload = MessagePayload(message: message)

        XCTAssertEqual(message.reasoningContent, "why")
        XCTAssertEqual(payload.reasoningContent, "why")
        guard case .parts(let parts) = payload.content else {
            return XCTFail("expected parts")
        }
        XCTAssertFalse(parts.contains { part in
            if case .reasoning = part { return true }
            return false
        })
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
