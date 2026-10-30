import Foundation
import Observation
import ZopediaKit

/// Owns the chat history and the conversation shown in the Chat tab.
@MainActor
@Observable
final class ChatStore {
    private(set) var threads: [ChatThread] = []
    private(set) var isLoading = true
    private(set) var errorMessage: String?
    private(set) var activeThread: ChatThread
    private(set) var isNewActive = true

    private let app: AppEnvironment
    private var newThreadID: String?

    init(app: AppEnvironment) {
        self.app = app
        let thread = Self.makeLocalThread()
        activeThread = thread
        newThreadID = thread.id
    }

    func load(forceRefresh: Bool) async {
        let cache = app.cache
        let cached: [ChatThread]
        if let cache {
            cached = await cache.cachedThreads()
            threads = cached
        } else {
            cached = []
        }
        isLoading = threads.isEmpty
        defer { isLoading = false }

        do {
            let remote = try await app.refreshThreads()
            let remoteIDs = Set(remote.map(\.id))
            // Chats the user chose not to log exist only on this device.
            // Replace the index dropped them; put them back.
            let localOnly = cached.filter { !remoteIDs.contains($0.id) }
            if let cache {
                for thread in localOnly {
                    if let stored = await cache.loadThread(thread.id) {
                        await cache.saveThread(thread, messages: stored.messages)
                    }
                }
            }
            threads = (remote + localOnly).sorted { $0.updatedAt > $1.updatedAt }
            if let fresh = threads.first(where: { $0.id == activeThread.id }) {
                activeThread = fresh
            }
            errorMessage = nil
        } catch let error as APIError where error == .cancelled {
            // Navigation away cancels the request; keep the cached list.
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            errorMessage = threads.isEmpty ? message : "Showing cached chats. \(message)"
        }
    }

    func startNewChat() {
        let thread = Self.makeLocalThread()
        activeThread = thread
        isNewActive = true
        newThreadID = thread.id
        errorMessage = nil
    }

    func open(_ thread: ChatThread) {
        activeThread = thread
        isNewActive = thread.id == newThreadID
    }

    func applyUpdate(_ updated: ChatThread) {
        if let position = threads.firstIndex(where: { $0.id == updated.id }) {
            threads[position] = updated
        } else {
            threads.insert(updated, at: 0)
        }

        if updated.id == newThreadID {
            newThreadID = nil
            isNewActive = false
        }
        if activeThread.id == updated.id {
            activeThread = updated
        }
    }

    func rename(_ thread: ChatThread, to title: String) async {
        let value = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value != thread.title else { return }
        guard let chat = app.chat, let cache = app.cache else { return }

        do {
            try await chat.renameThread(id: thread.id, title: value)
        } catch let error as APIError where Self.isNotFound(error) {
            // Local-only thread; rename it on this device only.
        } catch {
            errorMessage = "Could not rename: \(Self.message(for: error))"
            return
        }

        await cache.updateTitle(threadID: thread.id, title: value)
        if let position = threads.firstIndex(where: { $0.id == thread.id }) {
            threads[position].title = value
            if activeThread.id == thread.id {
                activeThread = threads[position]
            }
        }
        errorMessage = nil
    }

    func delete(_ thread: ChatThread) async {
        guard let chat = app.chat, let cache = app.cache else { return }

        do {
            try await chat.deleteThread(id: thread.id)
        } catch let error as APIError where Self.isNotFound(error) {
            // Local-only thread; delete it on this device only.
        } catch {
            errorMessage = "Could not delete: \(Self.message(for: error))"
            return
        }

        await cache.deleteThread(thread.id)
        threads.removeAll { $0.id == thread.id }
        if newThreadID == thread.id {
            newThreadID = nil
        }
        if activeThread.id == thread.id {
            startNewChat()
        }
        errorMessage = nil
    }

    private static func makeLocalThread() -> ChatThread {
        ChatThread(
            id: UUID().uuidString,
            title: "New Chat",
            createdAt: Date(),
            updatedAt: Date(),
            messageCount: 0
        )
    }

    private static func isNotFound(_ error: APIError) -> Bool {
        if case .http(let status, _) = error {
            return status == 404
        }
        return false
    }

    private static func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
