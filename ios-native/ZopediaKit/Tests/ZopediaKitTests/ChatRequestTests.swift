import XCTest
@testable import ZopediaKit

final class ChatRequestTests: XCTestCase {
    func testEncodingUsesSnakeCaseAndOmitsNils() throws {
        let request = ChatRequest(
            messages: [OutgoingMessage(role: "user", content: "hi")],
            sessionID: "thread-1",
            assistantMessageID: "assistant-1",
            parentID: "user-1"
        )
        let data = try JSONEncoder().encode(request)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )

        XCTAssertEqual(object["session_id"] as? String, "thread-1")
        XCTAssertEqual(object["assistant_message_id"] as? String, "assistant-1")
        XCTAssertEqual(object["parent_id"] as? String, "user-1")
        XCTAssertEqual(object["enable_tools"] as? Bool, true)
        XCTAssertEqual(object["stream"] as? Bool, true)
        XCTAssertNil(object["image_base64"])
        XCTAssertNil(object["model"])
    }

    func testImageIsIncludedWhenPresent() throws {
        let request = ChatRequest(
            messages: [OutgoingMessage(role: "user", content: "what is this")],
            imageBase64: "AAA"
        )
        let data = try JSONEncoder().encode(request)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        XCTAssertEqual(object["image_base64"] as? String, "AAA")
    }
}
