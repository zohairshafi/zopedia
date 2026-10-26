import XCTest
@testable import ZopediaKit

/// Opt-in tests against a real server.
///
///   ZOPEDIA_TEST_SERVER=http://127.0.0.1:8001 swift test --filter IntegrationTests
final class IntegrationTests: XCTestCase {
    func testStatusLoginAndHealth() async throws {
        guard let raw = ProcessInfo.processInfo.environment["ZOPEDIA_TEST_SERVER"],
              !raw.isEmpty else {
            throw XCTSkip("Set ZOPEDIA_TEST_SERVER to run integration tests")
        }

        let url = try ServerURL.normalize(raw)
        let store = MemoryTokenStore()
        let auth = AuthSession(baseURL: url, store: store)
        let client = APIClient(baseURL: url, auth: auth)
        let service = AuthService(client: client)

        let status = try await service.status()
        XCTAssertTrue(status.initialized)

        let health = try await service.health()
        XCTAssertEqual(health.status, "ok")

        let login = try await service.login(username: "local-user", password: "local-user")
        XCTAssertFalse(login.accessToken.isEmpty)
        try await auth.setSession(login)

        let hasTokens = await auth.hasTokens
        XCTAssertTrue(hasTokens)

        let stored = try store.load()
        XCTAssertEqual(stored?.accessToken, login.accessToken)
    }

    func testThreadLifecycle() async throws {
        guard let raw = ProcessInfo.processInfo.environment["ZOPEDIA_TEST_SERVER"],
              !raw.isEmpty else {
            throw XCTSkip("Set ZOPEDIA_TEST_SERVER to run integration tests")
        }

        let url = try ServerURL.normalize(raw)
        let auth = AuthSession(baseURL: url, store: MemoryTokenStore())
        let client = APIClient(baseURL: url, auth: auth)
        let authService = AuthService(client: client)
        let chat = ChatService(client: client)

        let login = try await authService.login(username: "local-user", password: "local-user")
        try await auth.setSession(login)

        let threadID = UUID().uuidString
        let userMessage = ChatMessage(
            id: UUID().uuidString,
            role: .user,
            content: .text("Hello"),
            createdAt: Date()
        )
        let assistantMessage = ChatMessage(
            id: UUID().uuidString,
            role: .assistant,
            content: .text("Hi there"),
            reasoningContent: "because",
            parentID: userMessage.id,
            createdAt: Date().addingTimeInterval(1)
        )

        _ = try await chat.saveThread(
            id: threadID,
            title: "Integration test",
            messages: [userMessage, assistantMessage]
        )

        let list = try await chat.listThreads()
        XCTAssertTrue(list.threads.contains { $0.id == threadID })

        let detail = try await chat.getThread(threadID)
        XCTAssertEqual(detail.messages.count, 2)
        XCTAssertEqual(detail.messages.last?.visibleText, "Hi there")
        XCTAssertEqual(detail.messages.last?.reasoningContent, "because")

        try await chat.renameThread(id: threadID, title: "Renamed")
        let renamed = try await chat.listThreads()
        XCTAssertEqual(renamed.threads.first { $0.id == threadID }?.title, "Renamed")

        try await chat.deleteThread(id: threadID)
        let after = try await chat.listThreads()
        XCTAssertFalse(after.threads.contains { $0.id == threadID })
    }

    func testStreamingChat() async throws {
        guard let raw = ProcessInfo.processInfo.environment["ZOPEDIA_TEST_SERVER"],
              !raw.isEmpty else {
            throw XCTSkip("Set ZOPEDIA_TEST_SERVER to run integration tests")
        }

        let url = try ServerURL.normalize(raw)
        let auth = AuthSession(baseURL: url, store: MemoryTokenStore())
        let client = APIClient(baseURL: url, auth: auth)
        let authService = AuthService(client: client)

        let login = try await authService.login(username: "local-user", password: "local-user")
        try await auth.setSession(login)

        var request = ChatRequest(
            messages: [
                OutgoingMessage(role: "user", content: "Reply with exactly the word: hello"),
            ],
            sessionID: UUID().uuidString,
            assistantMessageID: UUID().uuidString,
            parentID: UUID().uuidString
        )
        request.enableTools = false
        request.enableThinking = false
        request.maxTokens = 200

        var assembler = ChatStreamAssembler()
        let stream = await client.streamChat(request)
        for try await event in stream {
            assembler.apply(event)
            if event == .done { break }
        }

        XCTAssertTrue(assembler.isDone)
        XCTAssertTrue(assembler.hasContent)
        XCTAssertNil(assembler.errorMessage)
        XCTAssertFalse(assembler.text.isEmpty, "expected streamed text")
    }

    func testPDFExtractionAndWikiUpload() async throws {
        guard let raw = ProcessInfo.processInfo.environment["ZOPEDIA_TEST_SERVER"],
              !raw.isEmpty else {
            throw XCTSkip("Set ZOPEDIA_TEST_SERVER to run integration tests")
        }

        let url = try ServerURL.normalize(raw)
        let auth = AuthSession(baseURL: url, store: MemoryTokenStore())
        let client = APIClient(baseURL: url, auth: auth)
        let authService = AuthService(client: client)
        let attachments = AttachmentService(client: client)

        let login = try await authService.login(username: "local-user", password: "local-user")
        try await auth.setSession(login)

        let fixture = try XCTUnwrap(
            Bundle.module.url(
                forResource: "sample",
                withExtension: "pdf",
                subdirectory: "Fixtures"
            ),
            "missing sample.pdf fixture"
        )
        let pdfData = try Data(contentsOf: fixture)

        let extracted = try await attachments.extractPDF(
            data: pdfData,
            filename: "sample.pdf"
        )
        XCTAssertTrue(
            extracted.text.contains("Zopedia"),
            "unexpected extraction: \(extracted.text)"
        )

        let name = "native-test-\(UUID().uuidString).txt"
        let upload = try await attachments.uploadFiles([
            UploadFile(
                name: name,
                mimeType: "text/plain",
                data: Data("hello from the native test".utf8)
            ),
        ])
        XCTAssertTrue(
            upload.uploaded.contains { $0.hasSuffix(name) },
            "uploaded: \(upload.uploaded)"
        )
        XCTAssertTrue(upload.failed.isEmpty, "failed: \(upload.failed)")
    }

    func testWikiFilesPageAndQuery() async throws {
        guard let raw = ProcessInfo.processInfo.environment["ZOPEDIA_TEST_SERVER"],
              !raw.isEmpty else {
            throw XCTSkip("Set ZOPEDIA_TEST_SERVER to run integration tests")
        }

        let url = try ServerURL.normalize(raw)
        let auth = AuthSession(baseURL: url, store: MemoryTokenStore())
        let client = APIClient(baseURL: url, auth: auth)
        let authService = AuthService(client: client)
        let wiki = WikiService(client: client)

        let login = try await authService.login(username: "local-user", password: "local-user")
        try await auth.setSession(login)

        let files = try await wiki.files()
        let hasFixture = files.directories["concepts"]?.files.contains {
            $0.relativePath == "concepts/inflation.md"
        } ?? false
        guard hasFixture else {
            throw XCTSkip("Seed wiki/wiki/concepts/inflation.md to run the wiki test")
        }

        let page = try await wiki.page(path: "concepts/inflation.md")
        XCTAssertTrue(page.contains("sustained rise"))
        XCTAssertTrue(page.hasPrefix("---"), "raw frontmatter should be returned")

        let result = try await wiki.query(question: "What is inflation?")
        XCTAssertEqual(result.status, "ok")
        XCTAssertFalse(result.answer.isEmpty)
        XCTAssertTrue(result.contextPages.contains("concepts/inflation.md"))
    }
}
