import SwiftUI

extension Notification.Name {
    static let chatScrollToBottom = Notification.Name("zopedia.chat.scrollToBottom")
}

/// A tab bar we own, so re-tapping Chat can scroll to the latest message.
/// The system tab bar has no re-tap callback, and its scroll-to-top gesture
/// fights the chat's follow-the-stream behaviour.
struct ZTabBar: View {
    @Binding var selection: AppTab
    let showsHistory: Bool

    var body: some View {
        HStack(spacing: 0) {
            item(.chat, "Chat", "bubble.left.and.text.bubble.right")
            if showsHistory {
                item(.history, "History", "clock.arrow.circlepath")
            }
            item(.wiki, "Wiki", "books.vertical")
            item(.research, "Research", "flask")
            item(.settings, "Settings", "gearshape")
        }
        .padding(.top, 7)
        .padding(.bottom, 2)
        .background(ZTheme.background.ignoresSafeArea(edges: .bottom))
        .overlay(alignment: .top) {
            Rectangle()
                .fill(ZTheme.border)
                .frame(height: 0.5)
        }
    }

    private func item(_ tab: AppTab, _ title: String, _ icon: String) -> some View {
        let isSelected = selection == tab

        return Button {
            if isSelected {
                if tab == .chat {
                    NotificationCenter.default.post(name: .chatScrollToBottom, object: nil)
                }
            } else {
                selection = tab
            }
        } label: {
            VStack(spacing: 3) {
                Image(systemName: icon)
                    .font(.system(size: 20, weight: isSelected ? .semibold : .regular))
                Text(title)
                    .font(.caption2.weight(isSelected ? .semibold : .regular))
            }
            .foregroundStyle(isSelected ? ZTheme.primary : ZTheme.mutedForeground)
            .frame(maxWidth: .infinity)
            .frame(minHeight: 48)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
