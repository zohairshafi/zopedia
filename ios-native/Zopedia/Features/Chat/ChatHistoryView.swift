import SwiftUI
import ZopediaKit

struct ChatHistoryView: View {
    @Environment(\.scenePhase) private var scenePhase

    let store: ChatStore
    let onOpen: () -> Void

    @State private var renameTarget: ChatThread?
    @State private var renameText = ""

    var body: some View {
        NavigationStack {
            List {
                if let errorMessage = store.errorMessage {
                    Section {
                        Text(errorMessage)
                            .font(.callout)
                            .foregroundStyle(ZTheme.destructive)
                            .listRowBackground(ZTheme.background)
                    }
                }

                ForEach(store.threads) { thread in
                    Button {
                        store.open(thread)
                        onOpen()
                    } label: {
                        ChatThreadRow(thread: thread)
                    }
                    .buttonStyle(.plain)
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
                        .tint(ZTheme.destructive)
                    }
                    .contextMenu {
                        Button("Rename") { beginRename(thread) }
                        Button("Delete", role: .destructive) {
                            Task { await store.delete(thread) }
                        }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle("History")
            .overlay { emptyOverlay }
            .refreshable { await store.load(forceRefresh: true) }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        store.startNewChat()
                        onOpen()
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
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await store.load(forceRefresh: true) }
            }
        }
    }

    @ViewBuilder
    private var emptyOverlay: some View {
        if store.isLoading && store.threads.isEmpty {
            ProgressView()
        } else if store.threads.isEmpty && store.errorMessage == nil {
            ContentUnavailableView(
                "No chats yet",
                systemImage: "clock.arrow.circlepath",
                description: Text("Start a chat and it will appear here.")
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

struct ChatThreadRow: View {
    let thread: ChatThread

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(thread.title)
                .lineLimit(1)
                .foregroundStyle(ZTheme.foreground)
            HStack(spacing: 6) {
                Text(thread.updatedAt, format: .relative(presentation: .named))
                Text("·")
                Text(thread.messageCount == 1 ? "1 message" : "\(thread.messageCount) messages")
            }
            .font(.caption)
            .foregroundStyle(ZTheme.mutedForeground)
        }
        .padding(.vertical, 2)
    }
}
