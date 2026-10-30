import SwiftUI
import ZopediaKit

struct ResearchRunView: View {
    let model: ResearchViewModel
    let onDone: () -> Void

    @State private var isSubmitting = false
    @State private var showActivity = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header

                if model.phase == .awaitingApproval {
                    approvalCard
                }

                if !model.survey.isEmpty {
                    surveyCard
                }

                if model.hasReport {
                    reportCard
                }

                if !model.warnings.isEmpty {
                    warningsCard
                }

                activityCard

                if let error = model.errorMessage {
                    Text(error)
                        .font(.callout)
                        .foregroundStyle(ZTheme.destructive)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(ZTheme.destructive.opacity(0.08), in: ZTheme.cardShape)
                }

                if model.isTerminal {
                    Button {
                        onDone()
                    } label: {
                        HStack {
                            Spacer()
                            Text("New research")
                                .fontWeight(.semibold)
                            Spacer()
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(ZTheme.primary)
                }

                if !model.isTerminal {
                    Text("Keep the app open while a run is active. Switching tabs is fine, but backgrounding the app can cancel the run on the server.")
                        .font(.caption)
                        .foregroundStyle(ZTheme.mutedForeground)
                }
            }
            .padding()
        }
        .background(ZTheme.background)
        .navigationTitle(model.title ?? "Research")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !model.isTerminal {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Cancel", role: .destructive) {
                        Task { await model.cancel() }
                    }
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                phaseBadge
                Spacer()
                if model.totalRounds > 0 {
                    Text("Round \(min(max(model.currentRound, 1), model.totalRounds)) of \(model.totalRounds)")
                        .font(.caption)
                        .foregroundStyle(ZTheme.mutedForeground)
                }
            }

            Text(model.topic)
                .font(.title3.weight(.semibold))
                .foregroundStyle(ZTheme.foreground)

            ProgressView(value: model.progress)
                .tint(ZTheme.primary)

            HStack(spacing: 8) {
                if model.phase == .running {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(model.statusText)
                    .font(.callout)
                    .foregroundStyle(ZTheme.mutedForeground)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ZTheme.card, in: ZTheme.cardShape)
        .overlay { ZTheme.cardShape.stroke(ZTheme.border, lineWidth: 1) }
    }

    private var phaseBadge: some View {
        Text(model.phaseLabel)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(phaseColor)
            .background(phaseColor.opacity(0.10), in: Capsule())
    }

    private var phaseColor: Color {
        switch model.phase {
        case .running, .complete: return ZTheme.primary
        case .awaitingApproval: return .orange
        case .failed: return ZTheme.destructive
        case .cancelled: return ZTheme.mutedForeground
        }
    }

    private var approvalCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Approve sources for round \(model.awaitingRound ?? model.currentRound)")
                .font(.headline)
                .foregroundStyle(ZTheme.foreground)

            if model.sources.isEmpty {
                Text("No sources were found for this round.")
                    .font(.callout)
                    .foregroundStyle(ZTheme.mutedForeground)
            } else {
                ForEach(model.sources) { source in
                    sourceRow(source)
                }
            }

            HStack {
                Button {
                    Task {
                        isSubmitting = true
                        await model.approveSelected()
                        isSubmitting = false
                    }
                } label: {
                    Text("Approve \(model.selectedURLs.count)")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ZTheme.primary)
                .disabled(isSubmitting)

                Button("Skip round") {
                    Task {
                        isSubmitting = true
                        await model.skipRound()
                        isSubmitting = false
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(isSubmitting)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ZTheme.card, in: ZTheme.cardShape)
        .overlay { ZTheme.cardShape.stroke(ZTheme.border, lineWidth: 1) }
    }

    private func sourceRow(_ source: ResearchSource) -> some View {
        Toggle(isOn: selectionBinding(source)) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(source.title.isEmpty ? source.url : source.title)
                        .font(.callout)
                        .foregroundStyle(ZTheme.foreground)
                        .lineLimit(2)
                    if source.isTrusted {
                        badge("Trusted", color: ZTheme.primary)
                    }
                    if source.alreadyInWiki {
                        badge("Already in wiki", color: ZTheme.mutedForeground)
                    }
                }
                Text(source.url)
                    .font(.caption2)
                    .foregroundStyle(ZTheme.mutedForeground)
                    .lineLimit(1)
            }
        }
        .tint(ZTheme.primary)
        .disabled(source.alreadyInWiki)
    }

    private func selectionBinding(_ source: ResearchSource) -> Binding<Bool> {
        Binding(
            get: { model.selectedURLs.contains(source.url) },
            set: { isOn in
                model.setSourceSelected(source.url, selected: isOn)
            }
        )
    }

    private func badge(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.10), in: Capsule())
    }

    private var surveyCard: some View {
        DisclosureGroup {
            Text(model.survey)
                .font(.callout)
                .foregroundStyle(ZTheme.mutedForeground)
                .textSelection(.enabled)
                .padding(.top, 6)
        } label: {
            Text("Wiki survey")
                .font(.headline)
                .foregroundStyle(ZTheme.foreground)
        }
        .padding(14)
        .background(ZTheme.card, in: ZTheme.cardShape)
        .overlay { ZTheme.cardShape.stroke(ZTheme.border, lineWidth: 1) }
    }

    private var reportCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Report")
                    .font(.headline)
                    .foregroundStyle(ZTheme.foreground)
                Spacer()
                if model.reportIsStreaming {
                    ProgressView().controlSize(.small)
                }
            }

            if model.reportIsStreaming {
                Text(model.report)
                    .font(.body)
                    .foregroundStyle(ZTheme.foreground)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ZMarkdown(text: model.report)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(14)
        .background(ZTheme.card, in: ZTheme.cardShape)
        .overlay { ZTheme.cardShape.stroke(ZTheme.border, lineWidth: 1) }
    }

    private var warningsCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Warnings")
                .font(.headline)
                .foregroundStyle(.orange)
            ForEach(Array(model.warnings.enumerated()), id: \.offset) { _, warning in
                VStack(alignment: .leading, spacing: 2) {
                    Text(warning.url)
                        .font(.caption)
                        .foregroundStyle(ZTheme.foreground)
                        .lineLimit(1)
                    Text(warning.error)
                        .font(.caption2)
                        .foregroundStyle(ZTheme.mutedForeground)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.08), in: ZTheme.cardShape)
    }

    private var activityCard: some View {
        DisclosureGroup(isExpanded: $showActivity) {
            VStack(alignment: .leading, spacing: 6) {
                if model.activity.isEmpty {
                    Text("No activity yet.")
                        .font(.caption)
                        .foregroundStyle(ZTheme.mutedForeground)
                } else {
                    ForEach(Array(model.activity.suffix(30).enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.caption)
                            .foregroundStyle(ZTheme.mutedForeground)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .padding(.top, 6)
        } label: {
            Text("Activity")
                .font(.headline)
                .foregroundStyle(ZTheme.foreground)
        }
        .padding(14)
        .background(ZTheme.card, in: ZTheme.cardShape)
        .overlay { ZTheme.cardShape.stroke(ZTheme.border, lineWidth: 1) }
    }
}
