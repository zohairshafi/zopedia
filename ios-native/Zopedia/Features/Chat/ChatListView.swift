import SwiftUI
import ZopediaKit

struct ChatListView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.scenePhase) private var scenePhase

    @State private var threads: [ChatThread] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var renameTarget: ChatThread?
    @State private var renameText = ""
    @State private var newThread: ChatThread?
    @State private var selection: ChatThread?
    @State private var newThreadID: String?

    var body: some View {
        Group {
            if sizeClass == .regular {
                NavigationSplitView {
                    splitSidebar
                } detail: {
                    if let selection {
                        ChatDetailView(
                            thread: selection,
                            isNew: selection.id == newThreadID,
                            onThreadUpdated: applyUpdate
                        )
                        .id(selection.id)
                    } else {
                        ContentUnavailableView(
                            "Select a chat",
                            systemImage: "bubble.left.and.bubble.right",
                            description: Text("Choose a chat from the sidebar or start a new one.")
                        )
                    }
                }
            } else {
                NavigationStack {
                    compactSidebar
                        .navigationDestination(for: ChatThread.self) { thread in
                            ChatDetailView(
                                thread: thread,
                                isNew: false,
                                onThreadUpdated: applyUpdate
                            )
                        }
                        .navigationDestination(item: $newThread) { thread in
                            ChatDetailView(
                                thread: thread,
                                isNew: true,
                                onThreadUpdated: applyUpdate
                            )
                        }
                }
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await load(forceRefresh: true) }
            }
        }
    }

    private var splitSidebar: some View {
        List(selection: $selection) {
            errorSection
            ForEach(threads) { thread in
                ThreadRow(thread: thread)
                    .tag(thread)
                    .swipeActions(edge: .leading) {
                        Button {
                            beginRename(thread)
                        } label: {
                            Label("Rename", systemImage: "pencil")
                        }
                        .tint(.blue)
                    }
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) {
                            Task { await delete(thread) }
                        } label: {
                            Label("Delete", systemImage: "trash")
                        }
                    }
                    .contextMenu {
                        Button("Rename") { beginRename(thread) }
                        Button("Delete", role: .destructive) {
                            Task { await delete(thread) }
                        }
                    }
            }
        }
        .navigationTitle("Chats")
        .overlay { emptyOverlay }
        .refreshable { await load(forceRefresh: true) }
        .task { await load(forceRefresh: false) }
        .toolbar { chatToolbar }
        .alert("Rename chat", isPresented: renameAlertBinding) {
            TextField("Title", text: $renameText)
            Button("Cancel", role: .cancel) {}
            Button("Save") {
                if let thread = renameTarget { Task { await rename(thread) } }
            }
        }
    }

    private var compactSidebar: some View {
        List {
            errorSection
            ForEach(threads) { thread in
                NavigationLink(value: thread) {
                    ThreadRow(thread: thread)
                }
                .swipeActions(edge: .leading) {
                    Button {
                        beginRename(thread)
                    } label: {
                        Label("Rename", systemImage: "pencil")
                    }
                    .tint(.blue)
                }
                .swipeActions(edge: .trailing) {
                    Button(role: .destructive) {
                        Task { await delete(thread) }
                    } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
                .contextMenu {
                    Button("Rename") { beginRename(thread) }
                    Button("Delete", role: .destructive) {
                        Task { await delete(thread) }
                    }
                }
            }
        }
        .navigationTitle("Chats")
        .overlay { emptyOverlay }
        .refreshable { await load(forceRefresh: true) }
        .task { await load(forceRefresh: false) }
        .toolbar { chatToolbar }
        .alert("Rename chat", isPresented: renameAlertBinding) {
            TextField("Title", text: $renameText)
            Button("Cancel", role: .cancel) {}
            Button("Save") {
                if let thread = renameTarget { Task { await rename(thread) } }
            }
        }
    }

    @ViewBuilder
    private var errorSection: some View {
        if let errorMessage {
            Section {
                Text(errorMessage)
                    .font(.callout)
                    .foregroundStyle(.red)
            }
        }
    }

    @ViewBuilder
    private var emptyOverlay: some View {
        if isLoading && threads.isEmpty {
            ProgressView()
        } else if threads.isEmpty && errorMessage == nil {
            ContentUnavailableView(
                "No chats yet",
                systemImage: "bubble.left.and.bubble.right",
                description: Text("Chats started in the web or desktop app appear here.")
            )
        }
    }

    @ToolbarContentBuilder
    private var chatToolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button {
                startNewChat()
            } label: {
                Image(systemName: "square.and.pencil")
            }
            .accessibilityLabel("New chat")
        }
        ToolbarItem(placement: .topBarTrailing) {
            accountMenu
        }
    }

    private var renameAlertBinding: Binding<Bool> {
        Binding(
            get: { renameTarget != nil },
            set: { if !$0 { renameTarget = nil } }
        )
    }

    private var accountMenu: some View {
        Menu {
            if let serverURL = app.serverURL {
                Text(serverURL)
            }
            if let model = app.health?.llmModel, !model.isEmpty {
                Text(model)
            }
            Divider()
            Button("Disconnect", role: .destructive) {
                Task { await app.disconnect() }
            }
        } label: {
            Image(systemName: "person.crop.circle")
        }
        .accessibilityLabel("Account")
    }

    private func startNewChat() {
        let thread = ChatThread(
            id: UUID().uuidString,
            title: "New Chat",
            createdAt: Date(),
            updatedAt: Date(),
            messageCount: 0
        )

        if sizeClass == .regular {
            threads.insert(thread, at: 0)
            selection = thread
            newThreadID = thread.id
        } else {
            newThread = thread
        }
    }

    private func load(forceRefresh: Bool) async {
        if let cache = app.cache {
            threads = await cache.cachedThreads()
        }
        isLoading = threads.isEmpty
        defer { isLoading = false }

        do {
            threads = try await app.refreshThreads()
            if let selected = selection,
               let fresh = threads.first(where: { $0.id == selected.id }) {
                selection = fresh
            }
            errorMessage = nil
        } catch let error as APIError where error == .cancelled {
            // Navigation-away cancels the request; keep the cached list.
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            errorMessage = threads.isEmpty ? message : "Showing cached chats. \(message)"
        }
    }

    private func applyUpdate(_ updated: ChatThread) {
        if let position = threads.firstIndex(where: { $0.id == updated.id }) {
            threads[position] = updated
        } else {
            threads.insert(updated, at: 0)
        }
        if selection?.id == updated.id {
            selection = updated
        }
    }

    private func beginRename(_ thread: ChatThread) {
        renameTarget = thread
        renameText = thread.title
    }

    private func rename(_ thread: ChatThread) async {
        let title = renameText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, title != thread.title else { return }
        guard let chat = app.chat, let cache = app.cache else { return }

        do {
            try await chat.renameThread(id: thread.id, title: title)
            await cache.updateTitle(threadID: thread.id, title: title)
            if let position = threads.firstIndex(where: { $0.id == thread.id }) {
                threads[position].title = title
                if selection?.id == thread.id {
                    selection = threads[position]
                }
            }
            errorMessage = nil
        } catch {
            errorMessage = "Could not rename: \((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)"
        }
    }

    private func delete(_ thread: ChatThread) async {
        guard let chat = app.chat, let cache = app.cache else { return }

        do {
            try await chat.deleteThread(id: thread.id)
            await cache.deleteThread(thread.id)
            threads.removeAll { $0.id == thread.id }
            if selection?.id == thread.id {
                selection = nil
            }
            if newThreadID == thread.id {
                newThreadID = nil
            }
            errorMessage = nil
        } catch {
            errorMessage = "Could not delete: \((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)"
        }
    }
}

private struct ThreadRow: View {
    let thread: ChatThread

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(thread.title)
                .lineLimit(1)
            HStack(spacing: 6) {
                Text(thread.updatedAt, format: .relative(presentation: .named))
                Text("·")
                Text("\(thread.messageCount) messages")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }
}
