import Foundation
import SwiftUI
import ZopediaKit

struct ResearchSetupView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.dismiss) private var dismiss

    let editingID: String?
    let onStart: (ResearchConfig) -> Void

    @State private var topic = ""
    @State private var depth = "standard"
    @State private var rounds = 3
    @State private var sourcesPerRound = 15
    @State private var autoMode = false
    @State private var alpacaTrading = false
    @State private var sourceTypes: Set<String> = []
    @State private var timelimit = "m"
    @State private var trusted = ""
    @State private var blocked = ""
    @State private var scheduleMode = false
    @State private var interval = "daily"
    @State private var runHour = 9
    @State private var runDow = 0
    @State private var runDom = 1
    @State private var isLoadingDetail = false
    @State private var isSaving = false
    @State private var errorMessage: String?

    private struct SourceTypeOption: Identifiable {
        let id: String
        let label: String
    }

    private let sourceTypeOptions = [
        SourceTypeOption(id: "paper", label: "Papers"),
        SourceTypeOption(id: "webpage", label: "Webpages"),
        SourceTypeOption(id: "youtube", label: "YouTube"),
        SourceTypeOption(id: "tweet", label: "Tweets"),
        SourceTypeOption(id: "pdf", label: "PDFs"),
    ]

    private var isEditing: Bool { editingID != nil }

    private var canSubmit: Bool {
        !topic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isSaving
    }

    private var primaryTitle: String {
        if isEditing { return "Save changes" }
        return scheduleMode ? "Schedule research" : "Start research"
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Topic") {
                    TextField("What should be researched?", text: $topic, axis: .vertical)
                        .lineLimit(1...4)
                }

                Section("Depth") {
                    Picker("Depth", selection: $depth) {
                        Text("Shallow · 2 rounds · 10 sources").tag("shallow")
                        Text("Standard · 3 rounds · 15 sources").tag("standard")
                        Text("Deep · 5 rounds · 50 sources").tag("deep")
                        Text("Custom").tag("custom")
                    }
                    .onChange(of: depth) { _, value in
                        applyDepth(value)
                    }

                    Stepper("Rounds: \(rounds)", value: roundsBinding, in: 1...20)
                    Stepper("Sources per round: \(sourcesPerRound)", value: sourcesBinding, in: 1...100)
                }

                Section {
                    Toggle("Auto mode (skip source approval)", isOn: $autoMode)
                    Toggle("Allow proposed trades (approval still required)", isOn: $alpacaTrading)
                    Picker("Time sensitivity", selection: $timelimit) {
                        Text("Any time").tag("all")
                        Text("Past 24 hours").tag("d")
                        Text("Past week").tag("w")
                        Text("Past month").tag("m")
                        Text("Past year").tag("y")
                    }
                } header: {
                    Text("Options")
                } footer: {
                    if scheduleMode || isEditing {
                        Text("Scheduled runs always approve sources automatically.")
                    }
                }

                Section("Source types") {
                    ForEach(sourceTypeOptions) { option in
                        Toggle(option.label, isOn: sourceTypeBinding(option.id))
                    }
                }

                Section("Trusted sources") {
                    sourceEditor($trusted, placeholder: "One per line: arxiv.org, youtube.com/@channel")
                }

                Section("Blocked sources") {
                    sourceEditor($blocked, placeholder: "One per line")
                }

                Section {
                    Toggle("Run periodically", isOn: $scheduleMode)

                    if scheduleMode {
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
                    }
                } header: {
                    Text("Schedule")
                } footer: {
                    if scheduleMode {
                        Text("Scheduled runs happen on the server and post results to a chat thread.")
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(ZTheme.destructive)
                    }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Spacer()
                            if isSaving {
                                ProgressView()
                            } else {
                                Text(primaryTitle)
                                    .fontWeight(.semibold)
                            }
                            Spacer()
                        }
                    }
                    .disabled(!canSubmit)
                }
            }
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle(isEditing ? "Edit schedule" : "New research")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task { await loadDetailIfNeeded() }
            .onChange(of: scheduleMode) { _, isOn in
                if isOn { autoMode = true }
            }
        }
    }

    private func sourceEditor(_ text: Binding<String>, placeholder: String) -> some View {
        TextEditor(text: text)
            .frame(minHeight: 70)
            .overlay(alignment: .topLeading) {
                if text.wrappedValue.isEmpty {
                    Text(placeholder)
                        .font(.caption)
                        .foregroundStyle(ZTheme.mutedForeground)
                        .padding(.top, 8)
                        .padding(.leading, 5)
                        .allowsHitTesting(false)
                }
            }
    }

    private var roundsBinding: Binding<Int> {
        Binding(
            get: { rounds },
            set: { value in
                rounds = value
                depth = "custom"
            }
        )
    }

    private var sourcesBinding: Binding<Int> {
        Binding(
            get: { sourcesPerRound },
            set: { value in
                sourcesPerRound = value
                depth = "custom"
            }
        )
    }

    private func sourceTypeBinding(_ value: String) -> Binding<Bool> {
        Binding(
            get: { sourceTypes.contains(value) },
            set: { isOn in
                if isOn {
                    sourceTypes.insert(value)
                } else {
                    sourceTypes.remove(value)
                }
            }
        )
    }

    private func applyDepth(_ value: String) {
        guard !isLoadingDetail else { return }
        switch value {
        case "shallow":
            rounds = 2
            sourcesPerRound = 10
        case "standard":
            rounds = 3
            sourcesPerRound = 15
        case "deep":
            rounds = 5
            sourcesPerRound = 50
        default:
            break
        }
    }

    private func loadDetailIfNeeded() async {
        guard let editingID, let service = app.periodicResearch else { return }

        isLoadingDetail = true
        defer { isLoadingDetail = false }

        do {
            let detail = try await service.detail(id: editingID)
            topic = detail.topic
            rounds = detail.rounds
            sourcesPerRound = detail.sourcesPerRound
            depth = detail.researchDepth
            autoMode = true
            alpacaTrading = detail.alpacaTradingEnabled
            sourceTypes = Set(detail.sourceTypes)
            timelimit = detail.timelimit.isEmpty ? "all" : detail.timelimit
            trusted = detail.trustedSources.joined(separator: "\n")
            blocked = detail.blockedSources.joined(separator: "\n")
            scheduleMode = true
            interval = detail.intervalType
            if let hour = detail.runHour { runHour = hour }
            if let day = detail.runDow { runDow = day }
            if let day = detail.runDom { runDom = day }
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func submit() async {
        let trimmedTopic = topic.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedTopic.isEmpty else {
            errorMessage = "Enter a topic."
            return
        }

        if scheduleMode || isEditing {
            await saveSchedule(topic: trimmedTopic)
        } else {
            let config = makeConfig(topic: trimmedTopic)
            onStart(config)
            dismiss()
        }
    }

    private func makeConfig(topic: String) -> ResearchConfig {
        ResearchConfig(
            topic: topic,
            rounds: rounds,
            sourcesPerRound: sourcesPerRound,
            autoMode: autoMode,
            trustedSources: lines(from: trusted),
            blockedSources: lines(from: blocked),
            researchDepth: depth,
            sourceTypes: Array(sourceTypes).sorted(),
            timelimit: timelimit,
            alpacaTradingEnabled: alpacaTrading
        )
    }

    private func saveSchedule(topic: String) async {
        guard let service = app.periodicResearch else {
            errorMessage = "Not connected to a server."
            return
        }

        let request = PeriodicResearchRequest(
            topic: topic,
            rounds: rounds,
            sourcesPerRound: sourcesPerRound,
            trustedSources: lines(from: trusted),
            blockedSources: lines(from: blocked),
            researchDepth: depth,
            sourceTypes: Array(sourceTypes).sorted(),
            timelimit: timelimit,
            alpacaTradingEnabled: alpacaTrading,
            periodicInterval: interval,
            periodicHour: interval == "hourly" ? nil : runHour,
            periodicDow: interval == "weekly" ? runDow : nil,
            periodicDom: interval == "monthly" ? runDom : nil
        )

        isSaving = true
        errorMessage = nil
        defer { isSaving = false }

        do {
            if let editingID {
                _ = try await service.update(id: editingID, request: request)
            } else {
                _ = try await service.create(request)
            }
            dismiss()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func lines(from text: String) -> [String] {
        text.split(whereSeparator: { $0 == "\n" || $0 == "," })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func weekdayName(_ value: Int) -> String {
        let names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return names.indices.contains(value) ? names[value] : names[0]
    }
}
