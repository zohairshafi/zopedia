import SwiftUI

/// A small text action with a full 44 pt touch target.
struct TouchActionButton: View {
    let title: String
    var tint: Color = ZTheme.primary
    var role: ButtonRole?
    let action: () -> Void

    var body: some View {
        Button(role: role, action: action) {
            Text(title)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(tint)
                .padding(.horizontal, 10)
                .padding(.vertical, 10)
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
