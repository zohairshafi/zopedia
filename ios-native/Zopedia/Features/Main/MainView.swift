import SwiftUI

struct MainView: View {
    var body: some View {
        TabView {
            ChatListView()
                .tabItem {
                    Label("Chats", systemImage: "bubble.left.and.bubble.right")
                }

            WikiHomeView()
                .tabItem {
                    Label("Wiki", systemImage: "books.vertical")
                }
        }
    }
}
