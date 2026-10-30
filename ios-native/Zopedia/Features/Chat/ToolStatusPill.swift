import SwiftUI

struct ToolStatusPill: View {
    let status: String
    let since: Date

    private var isRunning: Bool {
        status.hasPrefix("Running")
    }

    var body: some View {
        TimelineView(.periodic(from: since, by: 1)) { context in
            HStack(spacing: 6) {
                Image(systemName: isRunning ? "terminal" : "globe")
                    .font(.caption2)
                Text(status)
                    .lineLimit(2)
                Text("\(Int(context.date.timeIntervalSince(since)))s")
                    .monospacedDigit()
                    .opacity(0.6)
            }
            .font(.caption)
            .foregroundStyle(ZTheme.primary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(ZTheme.primary.opacity(0.05), in: Capsule())
            .overlay {
                Capsule().stroke(ZTheme.primary.opacity(0.20), lineWidth: 1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal)
        .accessibilityLabel(status)
    }
}
