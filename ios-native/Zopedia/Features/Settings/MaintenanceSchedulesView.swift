import Foundation
import SwiftUI
import ZopediaKit

struct MaintenanceSchedulesView: View {
    @Environment(AppEnvironment.self) private var app

    @State private var schedules: [MaintenanceSchedule] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var actionMessage: String?
    @State private var showEditor = false
    @State private var editing: MaintenanceSchedule?
    @State private var runningID: String?
    @State private var deleting: MaintenanceSchedule?

    var body: some View {
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
                    editing = nil
                    showEditor = true
                } label: {
                    Label("New schedule", systemImage: "plus.circle.fill")
                        .foregroundStyle(ZTheme.primary)
                }
            }

            Section("Schedules") {
                if schedules.isEmpty {
                    Text("No maintenance is scheduled.")
                        .font(.callout)
                        .foregroundStyle(ZTheme.mutedForeground)
                } else {
                    ForEach(schedules) { schedule in
                        scheduleRow(schedule)
                    }
                }
            }

            Section {
                Text("Run now executes merge → retry-fallback → enrich → backlinks on the server. It can take several minutes and keeps running if you leave this screen.")
                    .font(.caption)
                    .foregroundStyle(ZTheme.mutedForeground)
            }
        }
        .scrollContentBackground(.hidden)
        .background(ZTheme.background)
        .navigationTitle("Maintenance")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $showEditor, onDismiss: {
            editing = nil
            Task { await load() }
        }) {
            MaintenanceScheduleEditorView(schedule: editing)
        }
        .confirmationDialog(
            "Delete this schedule?",
            isPresented: deleteBinding,
            presenting: deleting
        ) { schedule in
            Button("Delete", role: .destructive) {
                Task { await delete(schedule) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { schedule in
            Text(intervalDescription(schedule))
        }
    }

    private func scheduleRow(_ schedule: MaintenanceSchedule) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(intervalDescription(schedule))
                        .font(.headline)
                        .foregroundStyle(ZTheme.foreground)

                    if let next = schedule.nextRunAt {
                        Text("Next: \(next.formatted(date: .abbreviated, time: .shortened))")
                            .font(.caption)
                            .foregroundStyle(ZTheme.mutedForeground)
                    }

                    if let last = schedule.lastRunAt {
                        Text("Last: \(last.formatted(date: .abbreviated, time: .shortened))")
                            .font(.caption2)
                            .foregroundStyle(ZTheme.mutedForeground)
                    }

                    if schedule.withWebFill {
                        Text("Web fill")
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .foregroundStyle(ZTheme.primary)
                            .background(ZTheme.primary.opacity(0.10), in: Capsule())
                    }
                }

                Spacer()

                Toggle("", isOn: enabledBinding(schedule))
                    .labelsHidden()
                    .tint(ZTheme.primary)
            }

            HStack(spacing: 2) {
                TouchActionButton(title: "Run now") {
                    Task { await runNow(schedule) }
                }
                .disabled(runningID != nil)

                TouchActionButton(title: "Edit") {
                    editing = schedule
                    showEditor = true
                }

                TouchActionButton(
                    title: "Delete",
                    tint: ZTheme.destructive,
                    role: .destructive
                ) {
                    deleting = schedule
                }
            }

            if runningID == schedule.id {
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Running maintenance…")
                        .font(.caption)
                        .foregroundStyle(ZTheme.mutedForeground)
                }
            }
        }
        .opacity(schedule.enabled ? 1 : 0.6)
        .padding(.vertical, 2)
    }

    private func enabledBinding(_ schedule: MaintenanceSchedule) -> Binding<Bool> {
        Binding(
            get: {
                schedules.first(where: { $0.id == schedule.id })?.enabled ?? schedule.enabled
            },
            set: { value in
                if let index = schedules.firstIndex(where: { $0.id == schedule.id }) {
                    schedules[index].enabled = value
                }
                Task { await setEnabled(schedule, value) }
            }
        )
    }

    private var deleteBinding: Binding<Bool> {
        Binding(
            get: { deleting != nil },
            set: { if !$0 { deleting = nil } }
        )
    }

    private func intervalDescription(_ schedule: MaintenanceSchedule) -> String {
        var text = schedule.intervalType.capitalized
        if let hour = schedule.runHour {
            text += String(format: " at %02d:00", hour)
        }
        if let day = schedule.runDow, schedule.intervalType == "weekly" {
            text += ", \(weekdayName(day))"
        }
        if let day = schedule.runDom, schedule.intervalType == "monthly" {
            text += ", day \(day)"
        }
        return text
    }

    private func weekdayName(_ value: Int) -> String {
        let names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return names.indices.contains(value) ? names[value] : ""
    }

    private func load() async {
        guard let service = app.maintenance else {
            isLoading = false
            return
        }
        isLoading = schedules.isEmpty
        defer { isLoading = false }

        do {
            schedules = try await service.list().schedules
            errorMessage = nil
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func setEnabled(_ schedule: MaintenanceSchedule, _ enabled: Bool) async {
        guard let service = app.maintenance else { return }
        do {
            try await service.update(
                id: schedule.id,
                request: MaintenanceScheduleUpdateRequest(enabled: enabled)
            )
            errorMessage = nil
        } catch {
            errorMessage = "Could not update the schedule: \(message(for: error))"
            await load()
        }
    }

    private func runNow(_ schedule: MaintenanceSchedule) async {
        guard let service = app.maintenance else { return }
        runningID = schedule.id
        defer { runningID = nil }

        do {
            let response = try await service.runNow(id: schedule.id)
            actionMessage = response.status == "completed"
                ? "Maintenance completed."
                : "Maintenance finished with status \(response.status)."
            errorMessage = nil
            await load()
        } catch {
            errorMessage = "Maintenance did not report completion: \(message(for: error)). The server may still be running it."
        }
    }

    private func delete(_ schedule: MaintenanceSchedule) async {
        guard let service = app.maintenance else { return }
        deleting = nil
        do {
            try await service.delete(id: schedule.id)
            schedules.removeAll { $0.id == schedule.id }
            errorMessage = nil
        } catch {
            errorMessage = "Could not delete the schedule: \(message(for: error))"
        }
    }

    private func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}

struct MaintenanceScheduleEditorView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.dismiss) private var dismiss

    let schedule: MaintenanceSchedule?

    @State private var interval = "daily"
    @State private var withWebFill = false
    @State private var runHour = 3
    @State private var runDow = 0
    @State private var runDom = 1
    @State private var isSaving = false
    @State private var errorMessage: String?

    private var isEditing: Bool { schedule != nil }

    var body: some View {
        NavigationStack {
            Form {
                Section("Interval") {
                    Picker("Interval", selection: $interval) {
                        Text("Hourly").tag("hourly")
                        Text("Daily").tag("daily")
                        Text("Weekly").tag("weekly")
                        Text("Monthly").tag("monthly")
                    }

                    if interval != "hourly" {
                        Picker("Hour", selection: $runHour) {
                            ForEach(0..<24, id: \.self) { hour in
                                Text(String(format: "%02d:00", hour)).tag(hour)
                            }
                        }
                    }

                    if interval == "weekly" {
                        Picker("Weekday", selection: $runDow) {
                            ForEach(0..<7, id: \.self) { day in
                                Text(weekdayName(day)).tag(day)
                            }
                        }
                    }

                    if interval == "monthly" {
                        Picker("Day of month", selection: $runDom) {
                            ForEach(1...31, id: \.self) { day in
                                Text("\(day)").tag(day)
                            }
                        }
                    }

                    Toggle("Include web fill", isOn: $withWebFill)
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(ZTheme.destructive)
                    }
                }

                Section {
                    Button {
                        Task { await save() }
                    } label: {
                        HStack {
                            Spacer()
                            if isSaving {
                                ProgressView()
                            } else {
                                Text(isEditing ? "Save changes" : "Create schedule")
                                    .fontWeight(.semibold)
                            }
                            Spacer()
                        }
                    }
                    .disabled(isSaving)
                }
            }
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle(isEditing ? "Edit schedule" : "New schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .onAppear { prefill() }
        }
    }

    private func prefill() {
        guard let schedule else { return }
        interval = schedule.intervalType
        withWebFill = schedule.withWebFill
        if let hour = schedule.runHour { runHour = hour }
        if let day = schedule.runDow { runDow = day }
        if let day = schedule.runDom { runDom = day }
    }

    private func save() async {
        guard let service = app.maintenance else {
            errorMessage = "Not connected to a server."
            return
        }

        isSaving = true
        errorMessage = nil
        defer { isSaving = false }

        let hour: Int? = interval == "hourly" ? nil : runHour
        let dow: Int? = interval == "weekly" ? runDow : nil
        let dom: Int? = interval == "monthly" ? runDom : nil

        do {
            if let schedule {
                try await service.update(
                    id: schedule.id,
                    request: MaintenanceScheduleUpdateRequest(
                        intervalType: interval,
                        withWebFill: withWebFill,
                        runHour: hour,
                        runDow: dow,
                        runDom: dom
                    )
                )
            } else {
                _ = try await service.create(
                    MaintenanceScheduleCreateRequest(
                        intervalType: interval,
                        withWebFill: withWebFill,
                        runHour: hour,
                        runDow: dow,
                        runDom: dom
                    )
                )
            }
            dismiss()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func weekdayName(_ value: Int) -> String {
        let names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return names.indices.contains(value) ? names[value] : ""
    }
}
