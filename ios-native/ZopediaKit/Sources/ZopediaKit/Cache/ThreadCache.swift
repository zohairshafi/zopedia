import CryptoKit
import Foundation
import os

/// Per-server, per-user cache of thread lists and messages.
///
/// The server remains the source of truth. This cache exists for instant launch,
/// offline reading, and crash recovery. Failures are logged, never fatal.
public actor ThreadCache {
    public struct Index: Codable, Sendable {
        public var schemaVersion: Int
        public var subject: String
        public var threads: [ChatThread]
        public var deletedThreadIDs: Set<String>
    }

    public struct CachedThread: Codable, Sendable {
        public var schemaVersion: Int
        public var thread: ChatThread
        public var messages: [ChatMessage]
    }

    private static let schemaVersion = 1
    private static let logger = Logger(subsystem: "com.zopedia.client", category: "cache")

    private let subject: String
    private let directory: URL
    private let threadsDirectory: URL
    private let indexURL: URL

    public init(root: URL, serverURL: String, subject: String) throws {
        self.subject = subject
        let scope = Self.scopeKey(serverURL: serverURL, subject: subject)
        directory = root.appendingPathComponent(scope, isDirectory: true)
        threadsDirectory = directory.appendingPathComponent("threads", isDirectory: true)
        indexURL = directory.appendingPathComponent("index.json")

        try FileManager.default.createDirectory(
            at: threadsDirectory,
            withIntermediateDirectories: true
        )

        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableDirectory = directory
        try mutableDirectory.setResourceValues(values)
    }

    public func cachedThreads() -> [ChatThread] {
        let index = loadIndex()
        return index.threads
            .filter { !index.deletedThreadIDs.contains($0.id) }
            .sorted { $0.updatedAt > $1.updatedAt }
    }

    public func deletedThreadIDs() -> Set<String> {
        loadIndex().deletedThreadIDs
    }

    /// Replace the cached thread list with the server's response.
    @discardableResult
    public func replaceIndex(with threads: [ChatThread]) -> [ChatThread] {
        var index = loadIndex()
        index.schemaVersion = Self.schemaVersion
        index.subject = subject
        index.threads = threads.filter { !index.deletedThreadIDs.contains($0.id) }
        write(index, to: indexURL)
        return index.threads.sorted { $0.updatedAt > $1.updatedAt }
    }

    public func saveThread(_ thread: ChatThread, messages: [ChatMessage]) {
        write(
            CachedThread(
                schemaVersion: Self.schemaVersion,
                thread: thread,
                messages: messages
            ),
            to: threadURL(thread.id)
        )

        var index = loadIndex()
        if let position = index.threads.firstIndex(where: { $0.id == thread.id }) {
            index.threads[position] = thread
        } else if !index.deletedThreadIDs.contains(thread.id) {
            index.threads.append(thread)
        }
        write(index, to: indexURL)
    }

    public func loadThread(_ id: String) -> CachedThread? {
        read(CachedThread.self, from: threadURL(id))
    }

    public func updateTitle(threadID: String, title: String) {
        var index = loadIndex()
        if let position = index.threads.firstIndex(where: { $0.id == threadID }) {
            index.threads[position].title = title
            write(index, to: indexURL)
        }
        if var cached = loadThread(threadID) {
            cached.thread.title = title
            write(cached, to: threadURL(threadID))
        }
    }

    public func deleteThread(_ id: String) {
        var index = loadIndex()
        index.threads.removeAll { $0.id == id }
        index.deletedThreadIDs.insert(id)
        write(index, to: indexURL)
        do {
            try FileManager.default.removeItem(at: threadURL(id))
        } catch CocoaError.fileNoSuchFile {
            // Nothing to remove.
        } catch {
            Self.logger.error(
                "cache delete failed: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    public func clear() {
        do {
            try FileManager.default.removeItem(at: directory)
        } catch CocoaError.fileNoSuchFile {
            // Already empty.
        } catch {
            Self.logger.error("cache clear failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    // MARK: - Storage

    private func loadIndex() -> Index {
        if let index = read(Index.self, from: indexURL) {
            return index
        }
        return Index(
            schemaVersion: Self.schemaVersion,
            subject: subject,
            threads: [],
            deletedThreadIDs: []
        )
    }

    private func threadURL(_ id: String) -> URL {
        let safe = id.replacingOccurrences(of: "/", with: "_")
        return threadsDirectory.appendingPathComponent("\(safe).json")
    }

    private func write<T: Encodable>(_ value: T, to url: URL) {
        do {
            let data = try JSONEncoder.zopedia.encode(value)
            #if os(iOS)
            try data.write(
                to: url,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            #else
            try data.write(to: url, options: .atomic)
            #endif
        } catch {
            Self.logger.error(
                "cache write failed for \(url.lastPathComponent, privacy: .public): \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private func read<T: Decodable>(_ type: T.Type, from url: URL) -> T? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        do {
            return try JSONDecoder.zopedia.decode(type, from: data)
        } catch {
            Self.logger.error(
                "cache corrupt at \(url.lastPathComponent, privacy: .public): \(error.localizedDescription, privacy: .public)"
            )
            moveAside(url)
            return nil
        }
    }

    private func moveAside(_ url: URL) {
        let backup = url.appendingPathExtension("corrupt")
        do {
            try? FileManager.default.removeItem(at: backup)
            try FileManager.default.moveItem(at: url, to: backup)
        } catch {
            Self.logger.error(
                "cache recovery failed: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private static func scopeKey(serverURL: String, subject: String) -> String {
        let input = Data((serverURL + "\0" + subject).utf8)
        return SHA256.hash(data: input)
            .map { String(format: "%02x", $0) }
            .joined()
    }
}
