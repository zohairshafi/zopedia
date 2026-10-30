import XCTest
@testable import ZopediaKit

final class ChatHTMLExporterTests: XCTestCase {
    private let date = Date(timeIntervalSince1970: 1_700_000_000)

    func testRendersMarkdownTablesAndRoles() {
        let user = ChatMessage(
            id: "u1", role: .user, content: .text("Show me **numbers**."),
            createdAt: date
        )
        let assistant = ChatMessage(
            id: "a1", role: .assistant,
            content: .text("| Year | Rate |\n| --- | --- |\n| 2023 | 4.1% |"),
            createdAt: date
        )

        let html = ChatHTMLExporter.html(
            title: "Inflation", messages: [user, assistant]
        )

        XCTAssertTrue(html.contains("<strong>numbers</strong>"))
        XCTAssertTrue(html.contains("<table>"))
        XCTAssertTrue(html.contains("class=\"message user\""))
        XCTAssertTrue(html.contains("class=\"role\">Zopedia"))
        XCTAssertTrue(html.contains("<title>Inflation</title>"))
    }

    func testRendersToolCalls() {
        let tool = ToolCallPart(
            toolCallID: "c1",
            toolName: "search_wiki",
            args: .object(["query": .string("inflation")]),
            result: #"{"hits":2}"#
        )
        let message = ChatMessage(
            id: "a1", role: .assistant,
            content: .parts([.tool(tool), .text("Found two pages.")]),
            createdAt: date
        )

        let html = ChatHTMLExporter.html(title: "Tools", messages: [message])

        XCTAssertTrue(html.contains("search_wiki"))
        XCTAssertTrue(html.contains("Found two pages."))
        XCTAssertTrue(html.contains("&quot;hits&quot;"))
    }

    func testRawHTMLIsEscaped() {
        let message = ChatMessage(
            id: "u1", role: .user,
            content: .text("<script>alert(1)</script>"),
            createdAt: date
        )
        let html = ChatHTMLExporter.html(title: "Safe", messages: [message])
        XCTAssertFalse(html.contains("<script>alert(1)</script>"))
        XCTAssertTrue(html.contains("&lt;script&gt;"))
    }

    func testEscapesTitle() {
        let html = ChatHTMLExporter.html(
            title: "A < B & C", messages: [], generatedAt: date
        )
        XCTAssertTrue(html.contains("A &lt; B &amp; C"))
    }
}
