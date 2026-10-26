import XCTest
@testable import ZopediaKit

final class ChatModelTests: XCTestCase {
    func testThreadListDecoding() throws {
        let json = #"""
        {
          "threads": [
            {
              "id": "t1",
              "title": "Oil prices",
              "created_at": "2026-10-26T10:00:00.123456+00:00",
              "updated_at": "2026-10-26T11:30:00+00:00",
              "message_count": 7
            }
          ],
          "subject": "zohairshafi"
        }
        """#
        let response = try JSONDecoder.zopedia.decode(
            ThreadListResponse.self, from: Data(json.utf8)
        )
        XCTAssertEqual(response.subject, "zohairshafi")
        XCTAssertEqual(response.threads.count, 1)
        XCTAssertEqual(response.threads[0].title, "Oil prices")
        XCTAssertEqual(response.threads[0].messageCount, 7)

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        XCTAssertEqual(calendar.component(.hour, from: response.threads[0].updatedAt), 11)
    }

    func testThreadDetailWithStringContent() throws {
        let json = #"""
        {
          "thread": {
            "id": "t1",
            "title": "Hello",
            "created_at": "2026-10-26T10:00:00+00:00",
            "updated_at": "2026-10-26T10:00:00+00:00"
          },
          "messages": [
            {
              "id": "m1",
              "role": "user",
              "content": "What is this?",
              "created_at": "2026-10-26T10:00:01+00:00"
            }
          ]
        }
        """#
        let response = try JSONDecoder.zopedia.decode(
            ThreadDetailResponse.self, from: Data(json.utf8)
        )
        XCTAssertEqual(response.messages.count, 1)
        XCTAssertEqual(response.messages[0].role, .user)
        XCTAssertEqual(response.messages[0].visibleText, "What is this?")
    }

    func testStructuredContentIsParsedFromJSONString() throws {
        // The server stores list content with json.dumps.
        let parts = #"""
        [
          {"type":"reasoning","text":"thinking"},
          {"type":"tool-call","toolCallId":"c1","toolName":"search_wiki","args":{"q":"x"},"result":"ok"},
          {"type":"text","text":"answer"}
        ]
        """#
        let payload = try JSONSerialization.data(
            withJSONObject: [
                "id": "m1",
                "role": "assistant",
                "content": parts,
                "created_at": "2026-10-26T10:00:01+00:00",
            ]
        )
        let message = try JSONDecoder.zopedia.decode(ChatMessage.self, from: payload)
        guard case .parts(let decoded) = message.content else {
            return XCTFail("expected parts")
        }
        XCTAssertEqual(decoded.count, 3)
        XCTAssertEqual(message.visibleText, "answer")
        if case .tool(let tool) = decoded[1] {
            XCTAssertEqual(tool.toolName, "search_wiki")
            XCTAssertEqual(tool.result, "ok")
        } else {
            XCTFail("expected tool part")
        }
    }

    func testThinkTagsBecomeReasoning() {
        let message = ChatMessage(
            id: "m1",
            role: .assistant,
            content: .text("<think>step 1</think>The answer is 42.")
        )
        let normalized = message.normalized()
        XCTAssertEqual(normalized.visibleText, "The answer is 42.")
        XCTAssertEqual(normalized.reasoningContent, "step 1")
    }

    func testMessagePayloadUsesSnakeCase() throws {
        let message = ChatMessage(
            id: "m1",
            role: .assistant,
            content: .text("hi"),
            reasoningContent: "why",
            parentID: "u1",
            createdAt: Date(timeIntervalSince1970: 1_000)
        )
        let data = try JSONEncoder.zopedia.encode(MessagePayload(message: message))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["reasoning_content"] as? String, "why")
        XCTAssertEqual(object["parent_id"] as? String, "u1")
        XCTAssertNotNil(object["created_at"] as? String)
    }
}
