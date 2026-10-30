import SwiftUI
import ZopediaKit

/// The iPad Chat tab's thread sidebar.
struct ChatSidebarList: View {
    let store: ChatStore

    @State private var renameTarget: ChatThread?
    @State private var renameText = ""

    var body: some View {
        List(selection: selection) {
            if let errorMessage = store.errorMessage {
                Section {
                    Text(errorMessage)
                        .font(.callout)
                        .foregroundStyle(ZTheme.destructive)
                        .listRowBackground(ZTheme.background)
                }
            }

            ForEach(store.threads) { thread in
                ChatThreadRow(thread: thread)
                    .tag(thread.id)
                    .listRowBackground(ZTheme.background)
                    .swipeActions(edge: .leading) {
                        Button {
                            beginRename(thread)
                        } label: {
                            Label("Rename", systemImage: "pencil")
                        }
                        .tint(ZTheme.primary)
                    }
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) {
                            Task { await store.delete(thread) }
                        } label: {
                            Label("Delete", systemImage: "trash")
                        }
                    }
                    .contextMenu {
                        Button("Rename") { beginRename(thread) }
                        Button("Delete", role: .destructive) {
                            Task { await store.delete(thread) }
                        }
                    }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("Chat")
        .overlay { emptyOverlay }
        .refreshable { await store.load(forceRefresh: true) }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    store.startNewChat()
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "square.and.pencil")
                        Text("New chat")
                    }
                    .font(.subheadline.weight(.medium))
                    .contentShape(Rectangle())
                }
                .accessibilityLabel("New chat")
            }
        }
        .alert("Rename chat", isPresented: renameAlertBinding) {
            TextField("Title", text: $renameText)
            Button("Cancel", role: .cancel) {}
            Button("Save") {
                if let thread = renameTarget {
                    Task { await store.rename(thread, to: renameText) }
                }
            }
        }
    }

    private var selection: Binding<String?> {
        Binding(
            get: {
                store.threads.contains(where: { $0.id == store.activeThread.id })
                    ? store.activeThread.id
                    : nil
            },
            set: { id in
                guard let id,
                      let thread = store.threads.first(where: { $0.id == id }) else { return }
                store.open(thread)
            }
        )
    }

    @ViewBuilder
    private var emptyOverlay: some View {
        if store.isLoading && store.threads.isEmpty {
            ProgressView()
        } else if store.threads.isEmpty && store.errorMessage == nil {
            ContentUnavailableView(
                "No chats yet",
                systemImage: "bubble.left.and.bubble.right",
                description: Text("Start a chat to see it here.")
            )
        }
    }

    private var renameAlertBinding: Binding<Bool> {
        Binding(
            get: { renameTarget != nil },
            set: { if !$0 { renameTarget = nil } }
        )
    }

    private func beginRename(_ thread: ChatThread) {
        renameTarget = thread
        renameText = thread.title
    }
}
