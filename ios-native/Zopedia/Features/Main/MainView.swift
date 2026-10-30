import SwiftUI
import ZopediaKit

enum AppTab: Hashable {
    case chat
    case history
    case wiki
    case research
    case settings
}

struct MainView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.horizontalSizeClass) private var sizeClass

    @State private var tab: AppTab = .chat
    @State private var store: ChatStore?
    @State private var wikiPendingPath: String?

    var body: some View {
        Group {
            if let store {
                tabs(store)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(ZTheme.background)
            }
        }
        .onAppear {
            guard store == nil else { return }
            let created = ChatStore(app: app)
            store = created
            Task {
                await created.load(forceRefresh: false)
            }
        }
    }

    private func tabs(_ store: ChatStore) -> some View {
        TabView(selection: $tab) {
            ChatTabView(store: store)
                .tabItem {
                    Label("Chat", systemImage: "bubble.left.and.text.bubble.right")
                }
                .tag(AppTab.chat)

            if sizeClass == .compact {
                ChatHistoryView(store: store) {
                    tab = .chat
                }
                .tabItem {
                    Label("History", systemImage: "clock.arrow.circlepath")
                }
                .tag(AppTab.history)
            }

            WikiHomeView(pendingPath: $wikiPendingPath)
                .tabItem {
                    Label("Wiki", systemImage: "books.vertical")
                }
                .tag(AppTab.wiki)

            ResearchHomeView()
                .tabItem {
                    Label("Research", systemImage: "flask")
                }
                .tag(AppTab.research)

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
                .tag(AppTab.settings)
        }
        .tint(ZTheme.primary)
        .background(TabBarTapObserver())
        .environment(\.openURL, OpenURLAction { url in
            if let path = WikiLinkPreprocessor.pagePath(from: url) {
                wikiPendingPath = path
                tab = .wiki
                return .handled
            }
            return .systemAction
        })
        .onChange(of: sizeClass) { _, newValue in
            if newValue == .regular, tab == .history {
                tab = .chat
            }
        }
    }
}

private struct ChatTabView: View {
    @Environment(\.horizontalSizeClass) private var sizeClass

    let store: ChatStore

    var body: some View {
        if sizeClass == .regular {
            NavigationSplitView {
                ChatSidebarList(store: store)
            } detail: {
                conversation
            }
        } else {
            NavigationStack {
                conversation
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
            }
        }
    }

    private var conversation: some View {
        ChatDetailView(
            thread: store.activeThread,
            isNew: store.isNewActive,
            onThreadUpdated: store.applyUpdate
        )
        .id(store.activeThread.id)
    }
}
