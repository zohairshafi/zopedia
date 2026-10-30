import SwiftUI

/// The web composer's pill row, sized for a phone: scrolls horizontally.
struct ChatOptionsBar: View {
    @Bindable var options: ChatOptionsStore

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                thinkingMenu
                chip(
                    title: "Search",
                    icon: "globe",
                    isOn: options.webSearch
                ) {
                    options.webSearch.toggle()
                }
                chip(
                    title: "DB",
                    icon: "cylinder",
                    isOn: options.database
                ) {
                    options.database.toggle()
                }
                chip(
                    title: "Alpaca",
                    icon: "chart.line.uptrend.xyaxis",
                    isOn: options.alpacaData
                ) {
                    options.alpacaData.toggle()
                }
                chip(
                    title: "Trade",
                    icon: "arrow.left.arrow.right",
                    isOn: options.alpacaTrade
                ) {
                    options.alpacaTrade.toggle()
                }
            }
            .padding(.horizontal)
        }
    }

    private var thinkingMenu: some View {
        Menu {
            Button {
                options.thinking = .serverDefault
            } label: {
                menuLabel("Default", selected: options.thinking == .serverDefault)
            }
            Button {
                options.thinking = .off
            } label: {
                menuLabel("Off", selected: options.thinking == .off)
            }
            Button {
                options.thinking = .on
            } label: {
                menuLabel("On", selected: options.thinking == .on)
            }

            Divider()

            ForEach(["low", "medium", "high", "max"], id: \.self) { level in
                Button {
                    options.thinking = .effort(level)
                } label: {
                    menuLabel(
                        "Effort: \(level.capitalized)",
                        selected: options.thinking == .effort(level)
                    )
                }
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: options.thinking.isActive ? "lightbulb.fill" : "lightbulb")
                Text(options.thinking.isActive ? "Think: \(options.thinking.label)" : "Think")
            }
            .font(.caption.weight(.medium))
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .foregroundStyle(options.thinking.isActive ? ZTheme.primary : ZTheme.mutedForeground)
            .background(
                options.thinking.isActive ? ZTheme.primary.opacity(0.10) : ZTheme.muted,
                in: Capsule()
            )
        }
        .accessibilityLabel("Thinking mode: \(options.thinking.label)")
    }

    private func menuLabel(_ title: String, selected: Bool) -> some View {
        HStack {
            Text(title)
            if selected {
                Image(systemName: "checkmark")
            }
        }
    }

    private func chip(
        title: String,
        icon: String,
        isOn: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                Text(title)
            }
            .font(.caption.weight(.medium))
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .foregroundStyle(isOn ? ZTheme.primary : ZTheme.mutedForeground)
            .background(isOn ? ZTheme.primary.opacity(0.10) : ZTheme.muted, in: Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title): \(isOn ? "on" : "off")")
    }
}
