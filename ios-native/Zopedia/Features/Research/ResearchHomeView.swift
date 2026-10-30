import Foundation
import SwiftUI
import ZopediaKit

struct ResearchHomeView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.scenePhase) private var scenePhase

    @State private var run: ResearchViewModel?
    @State private var configs: [PeriodicResearchSummary] = []
    @State private var approvals: [PendingTradeApproval] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var actionMessage: String?
    @State private var showSetup = false
    @State private var editingID: String?
    @State private var runningConfigID: String?
    @State private var deleting: PeriodicResearchSummary?
    @State private var decidingID: String?

    var body: some View {
        NavigationStack {
            Group {
                if let run {
                    ResearchRunView(model: run) {
                        Task {
                            if !run.isTerminal { await run.cancel() }
                            self.run = nil
                            await load()
                        }
                    }
                } else {
                    home
                }
            }
            .background(ZTheme.background)
            .navigationTitle("Research")
            .toolbar {
                if run == nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            editingID = nil
                            showSetup = true
                        } label: {
                            Image(systemName: "plus")
                        }
                        .accessibilityLabel("New research")
                    }
                }
            }
            .sheet(isPresented: $showSetup, onDismiss: {
                editingID = nil
                Task { await load() }
            }) {
                ResearchSetupView(editingID: editingID) { config in
                    let model = ResearchViewModel(app: app)
                    run = model
                    model.start(config: config)
                }
            }
        }
        .task { await load() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await loadApprovals() }
            }
        }
        .confirmationDialog(
            "Delete this scheduled research?",
            isPresented: deleteBinding,
            presenting: deleting
        ) { config in
            Button("Delete", role: .destructive) {
                Task { await delete(config) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { config in
            Text(config.topic)
        }
    }

    private var home: some View {
        List {
            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .font(.callout)
                        .foregroundStyle(ZTheme.destructive)
                }
            }

            if let actionMessage {
                Section {
                    Text(actionMessage)
                        .font(.callout)
                        .foregroundStyle(ZTheme.mutedForeground)
                }
            }

            Section {
                Button {
                    editingID = nil
                    showSetup = true
                } label: {
                    Label("New research", systemImage: "plus.circle.fill")
                        .font(.headline)
                        .foregroundStyle(ZTheme.primary)
                }
            }

            Section("Scheduled research") {
                if configs.isEmpty {
                    Text("No scheduled research yet.")
                        .font(.callout)
                        .foregroundStyle(ZTheme.mutedForeground)
                } else {
                    ForEach(configs) { config in
                        scheduleRow(config)
                    }
                }
            }

            Section("Pending trade approvals") {
                if approvals.isEmpty {
                    Text("No orders are waiting for approval.")
                        .font(.callout)
                        .foregroundStyle(ZTheme.mutedForeground)
                } else {
                    ForEach(approvals) { approval in
                        approvalRow(approval)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(ZTheme.background)
        .overlay {
            if isLoading && configs.isEmpty && approvals.isEmpty {
                ProgressView()
            }
        }
        .refreshable { await load() }
    }

    private func scheduleRow(_ config: PeriodicResearchSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(config.topic)
                        .font(.headline)
                        .foregroundStyle(ZTheme.foreground)
                    Text(intervalDescription(config))
                        .font(.caption)
                        .foregroundStyle(ZTheme.mutedForeground)
                    Text("\(config.rounds) rounds × \(config.sourcesPerRound) sources")
                        .font(.caption2)
                        .foregroundStyle(ZTheme.mutedForeground)
                }

                Spacer()

                Toggle("", isOn: enabledBinding(config))
                    .labelsHidden()
                    .tint(ZTheme.primary)
            }

            HStack(spacing: 2) {
                TouchActionButton(title: "Run now") {
                    Task { await runNow(config) }
                }
                .disabled(runningConfigID != nil)

                TouchActionButton(title: "Edit") {
                    editingID = config.id
                    showSetup = true
                }

                TouchActionButton(
                    title: "Delete",
                    tint: ZTheme.destructive,
                    role: .destructive
                ) {
                    deleting = config
                }

                if runningConfigID == config.id {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            if config.enabled == false {
                Text("Paused")
                    .font(.caption2)
                    .foregroundStyle(ZTheme.mutedForeground)
            }
        }
        .opacity(config.enabled ? 1 : 0.6)
        .padding(.vertical, 2)
    }

    private func intervalDescription(_ config: PeriodicResearchSummary) -> String {
        var text = config.intervalType.capitalized
        if let hour = config.runHour {
            text += String(format: " at %02d:00", hour)
        }
        if let day = config.runDow, config.intervalType == "weekly" {
            text += ", \(weekdayName(day))"
        }
        if let day = config.runDom, config.intervalType == "monthly" {
            text += ", day \(day)"
        }
        if let next = config.nextRunAt {
            text += " · next \(next.formatted(date: .abbreviated, time: .shortened))"
        }
        return text
    }

    private func enabledBinding(_ config: PeriodicResearchSummary) -> Binding<Bool> {
        Binding(
            get: {
                configs.first(where: { $0.id == config.id })?.enabled ?? config.enabled
            },
            set: { value in
                if let index = configs.firstIndex(where: { $0.id == config.id }) {
                    configs[index].enabled = value
                }
                Task { await setEnabled(config, value) }
            }
        )
    }

    private func approvalRow(_ approval: PendingTradeApproval) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("\(approval.side) \(approval.quantity) \(approval.symbol)")
                    .font(.headline)
                    .foregroundStyle(ZTheme.foreground)
                Spacer()
                CountdownText(expiresAt: approval.expiresAt)
            }

            Text(approval.orderType.isEmpty ? "Order" : "\(approval.orderType) order")
                .font(.caption)
                .foregroundStyle(ZTheme.mutedForeground)

            if let rationale = approval.rationale, !rationale.isEmpty {
                Text(rationale)
                    .font(.callout)
                    .foregroundStyle(ZTheme.mutedForeground)
                    .lineLimit(4)
            }

            HStack {
                Button("Approve & place") {
                    Task { await decide(approval, approve: true) }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(ZTheme.primary)
                .disabled(decidingID != nil || isExpired(approval))

                Button("Reject") {
                    Task { await decide(approval, approve: false) }
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .tint(ZTheme.mutedForeground)
                .disabled(decidingID != nil || isExpired(approval))

                if decidingID == approval.id {
                    ProgressView().controlSize(.small)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func isExpired(_ approval: PendingTradeApproval) -> Bool {
        guard let expiresAt = approval.expiresAt else { return false }
        return expiresAt < Date()
    }

    private var deleteBinding: Binding<Bool> {
        Binding(
            get: { deleting != nil },
            set: { if !$0 { deleting = nil } }
        )
    }

    private func load() async {
        isLoading = configs.isEmpty && approvals.isEmpty
        defer { isLoading = false }

        var firstError: String?

        if let service = app.periodicResearch {
            do {
                configs = try await service.list().configs
            } catch {
                firstError = message(for: error)
            }
        }

        if let service = app.trading {
            do {
                approvals = try await service.pendingApprovals().approvals
            } catch {
                if firstError == nil { firstError = message(for: error) }
            }
        }

        errorMessage = firstError
    }

    private func loadApprovals() async {
        guard let service = app.trading else { return }
        do {
            approvals = try await service.pendingApprovals().approvals
            errorMessage = nil
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func setEnabled(_ config: PeriodicResearchSummary, _ enabled: Bool) async {
        guard let service = app.periodicResearch else { return }
        do {
            _ = try await service.setEnabled(id: config.id, enabled: enabled)
            errorMessage = nil
        } catch {
            errorMessage = "Could not update the schedule: \(message(for: error))"
            await load()
        }
    }

    private func runNow(_ config: PeriodicResearchSummary) async {
        guard let service = app.periodicResearch else { return }
        runningConfigID = config.id
        defer { runningConfigID = nil }

        do {
            try await service.runNow(id: config.id)
            actionMessage = "Started “\(config.topic)”. Results will appear in a chat thread."
            errorMessage = nil
            await load()
        } catch {
            errorMessage = "Could not start the run: \(message(for: error))"
        }
    }

    private func delete(_ config: PeriodicResearchSummary) async {
        guard let service = app.periodicResearch else { return }
        deleting = nil
        do {
            try await service.delete(id: config.id)
            configs.removeAll { $0.id == config.id }
            errorMessage = nil
        } catch {
            errorMessage = "Could not delete the schedule: \(message(for: error))"
        }
    }

    private func decide(_ approval: PendingTradeApproval, approve: Bool) async {
        guard let service = app.trading else { return }
        decidingID = approval.id
        defer { decidingID = nil }

        do {
            if approve {
                _ = try await service.approve(id: approval.id)
                actionMessage = "Order approved."
            } else {
                _ = try await service.reject(id: approval.id)
                actionMessage = "Order rejected."
            }
            errorMessage = nil
            await loadApprovals()
        } catch {
            errorMessage = "Could not record the decision: \(message(for: error))"
            await loadApprovals()
        }
    }

    private func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }

    private func weekdayName(_ value: Int) -> String {
        let names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return names.indices.contains(value) ? names[value] : ""
    }
}

private struct CountdownText: View {
    let expiresAt: Date?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            Text(label(at: context.date))
                .font(.caption)
                .foregroundStyle(expired(at: context.date) ? ZTheme.destructive : ZTheme.mutedForeground)
        }
    }

    private func expired(at date: Date) -> Bool {
        guard let expiresAt else { return false }
        return expiresAt <= date
    }

    private func label(at date: Date) -> String {
        guard let expiresAt else { return "" }
        if expiresAt <= date { return "Expired" }
        let minutes = max(1, Int(expiresAt.timeIntervalSince(date) / 60))
        return "\(minutes)m left"
    }
}
