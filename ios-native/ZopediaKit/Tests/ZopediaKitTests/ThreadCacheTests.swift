import XCTest
@testable import ZopediaKit

final class ThreadCacheTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("zopedia-cache-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func thread(id: String, title: String, updated: TimeInterval = 0) -> ChatThread {
        ChatThread(
            id: id,
            title: title,
            createdAt: Date(timeIntervalSince1970: 1_000),
            updatedAt: Date(timeIntervalSince1970: 1_000 + updated),
            messageCount: 2
        )
    }

    func testReplaceIndexAndReadBack() async throws {
        let cache = try ThreadCache(root: root, serverURL: "http://a", subject: "u")
        let threads = [thread(id: "t1", title: "One"), thread(id: "t2", title: "Two", updated: 10)]

        let stored = await cache.replaceIndex(with: threads)
        XCTAssertEqual(stored.map(\.id), ["t2", "t1"])
        let cached = await cache.cachedThreads()
        XCTAssertEqual(cached.map(\.id), ["t2", "t1"])
    }

    func testThreadRoundTrip() async throws {
        let cache = try ThreadCache(root: root, serverURL: "http://a", subject: "u")
        let message = ChatMessage(id: "m1", role: .user, content: .text("hello"))
        let saved = thread(id: "t1", title: "One")

        await cache.saveThread(saved, messages: [message])
        let loaded = await cache.loadThread("t1")

        XCTAssertEqual(loaded?.thread.title, "One")
        XCTAssertEqual(loaded?.messages.first?.visibleText, "hello")
    }

    func testDeleteAddsTombstoneAndSurvivesServerRefresh() async throws {
        let cache = try ThreadCache(root: root, serverURL: "http://a", subject: "u")
        await cache.replaceIndex(with: [thread(id: "t1", title: "One")])
        await cache.deleteThread("t1")

        let cached = await cache.cachedThreads()
        XCTAssertTrue(cached.isEmpty)
        let deleted = await cache.deletedThreadIDs()
        XCTAssertTrue(deleted.contains("t1"))

        // A stale server list must not resurrect it.
        await cache.replaceIndex(with: [thread(id: "t1", title: "One")])
        let afterRefresh = await cache.cachedThreads()
        XCTAssertTrue(afterRefresh.isEmpty)
    }

    func testUpdateTitleUpdatesIndexAndThread() async throws {
        let cache = try ThreadCache(root: root, serverURL: "http://a", subject: "u")
        await cache.saveThread(thread(id: "t1", title: "Old"), messages: [])

        await cache.updateTitle(threadID: "t1", title: "New")

        let cached = await cache.cachedThreads()
        XCTAssertEqual(cached.first?.title, "New")
        let loaded = await cache.loadThread("t1")
        XCTAssertEqual(loaded?.thread.title, "New")
    }

    func testScopesAreIsolated() async throws {
        let a = try ThreadCache(root: root, serverURL: "http://a", subject: "u1")
        let b = try ThreadCache(root: root, serverURL: "http://a", subject: "u2")

        await a.replaceIndex(with: [thread(id: "t1", title: "One")])

        let bThreads = await b.cachedThreads()
        XCTAssertTrue(bThreads.isEmpty)
    }

    func testCorruptIndexIsMovedAsideAndRecoversEmpty() async throws {
        let cache = try ThreadCache(root: root, serverURL: "http://a", subject: "u")
        await cache.replaceIndex(with: [thread(id: "t1", title: "One")])

        let scopes = try FileManager.default.contentsOfDirectory(
            at: root, includingPropertiesForKeys: nil
        )
        let indexURL = try XCTUnwrap(scopes.first).appendingPathComponent("index.json")
        try Data("not json".utf8).write(to: indexURL)

        let cached = await cache.cachedThreads()
        XCTAssertTrue(cached.isEmpty)

        let corrupt = indexURL.appendingPathExtension("corrupt")
        XCTAssertTrue(FileManager.default.fileExists(atPath: corrupt.path))
    }
}
