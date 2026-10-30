import SwiftUI
import ZopediaKit

struct WikiEnvView: View {
    @Environment(AppEnvironment.self) private var app

    @State private var config: WikiEnvConfig?
    @State private var draft: [String: String] = [:]
    @State private var cleared: Set<String> = []
    @State private var query = ""
    @State private var restart = true
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var result: WikiEnvSetResponse?
    @State private var validationErrors: [String: String] = [:]

    var body: some View {
        List {
            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .font(.callout)
                        .foregroundStyle(ZTheme.destructive)
                }
            }

            if let result {
                Section("Last apply") {
                    if result.restartScheduled {
                        Text("Backend restart scheduled. The connection may drop briefly.")
                            .font(.callout)
                            .foregroundStyle(ZTheme.primary)
                    }
                    Text("Updated \(result.updated.count), cleared \(result.cleared.count).")
                        .font(.callout)
                        .foregroundStyle(ZTheme.mutedForeground)
                    ForEach(result.invalid.sorted(by: { $0.key < $1.key }), id: \.key) { name, message in
                        Text("\(name): \(message)")
                            .font(.caption)
                            .foregroundStyle(ZTheme.destructive)
                    }
                }
            }

            if let config {
                Section {
                    if config.restartSupported {
                        Toggle("Restart backend after applying", isOn: $restart)
                            .tint(ZTheme.primary)
                        Text("Saving with restart enabled briefly disconnects the server.")
                            .font(.caption)
                            .foregroundStyle(ZTheme.mutedForeground)
                    } else {
                        Text("Restarting the backend is not available on this server.")
                            .font(.caption)
                            .foregroundStyle(ZTheme.mutedForeground)
                    }
                }
            }

            Section("Variables") {
                if isLoading && config == nil {
                    ProgressView()
                } else {
                    ForEach(filteredVariables) { variable in
                        variableRow(variable)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(ZTheme.background)
        .navigationTitle("Wiki behaviour")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: "Filter variables")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await apply() }
                } label: {
                    if isSaving {
                        ProgressView()
                    } else {
                        Text("Apply (\(changeCount))")
                    }
                }
                .disabled(changeCount == 0 || isSaving)
            }
        }
        .task { await load() }
    }

    private var filteredVariables: [WikiEnvVariable] {
        guard let config else { return [] }
        let sorted = config.variables.sorted {
            $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return sorted }
        return sorted.filter {
            $0.name.localizedCaseInsensitiveContains(trimmed)
                || $0.description.localizedCaseInsensitiveContains(trimmed)
        }
    }

    private var changeCount: Int {
        guard let config else { return 0 }
        return config.variables.reduce(0) { count, variable in
            count + (isChanged(variable) ? 1 : 0)
        }
    }

    private func isChanged(_ variable: WikiEnvVariable) -> Bool {
        if cleared.contains(variable.name) {
            return variable.hasOverride
        }
        guard let value = draft[variable.name] else { return false }
        return value != variable.currentValue
    }

    @ViewBuilder
    private func variableRow(_ variable: WikiEnvVariable) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(variable.name)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(ZTheme.foreground)
                    .lineLimit(1)

                Spacer()

                if cleared.contains(variable.name) {
                    Text("Reset")
                        .font(.caption2)
                        .foregroundStyle(ZTheme.primary)
                } else if variable.hasOverride {
                    Text("Override")
                        .font(.caption2)
                        .foregroundStyle(ZTheme.primary)
                }
            }

            if !variable.description.isEmpty {
                Text(variable.description)
                    .font(.caption2)
                    .foregroundStyle(ZTheme.mutedForeground)
            }

            switch variable.kind {
            case "bool":
                Toggle("", isOn: boolBinding(variable))
                    .labelsHidden()
                    .tint(ZTheme.primary)
            case "int", "float":
                TextField("Value", text: textBinding(variable))
                    .keyboardType(.numbersAndPunctuation)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(.callout, design: .monospaced))
            default:
                TextField("Value", text: textBinding(variable))
                    .textFieldStyle(.roundedBorder)
                    .font(.system(.callout, design: .monospaced))
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }

            HStack(spacing: 10) {
                Text("Default: \(variable.defaultValue)")
                    .lineLimit(1)
                if variable.hasOverride || cleared.contains(variable.name) {
                    Button("Reset to default") {
                        reset(variable)
                    }
                    .font(.caption2)
                    .buttonStyle(.plain)
                    .foregroundStyle(ZTheme.primary)
                }
            }
            .font(.caption2)
            .foregroundStyle(ZTheme.mutedForeground)

            if let message = validationErrors[variable.name] {
                Text(message)
                    .font(.caption2)
                    .foregroundStyle(ZTheme.destructive)
            }
        }
        .padding(.vertical, 4)
    }

    private func textBinding(_ variable: WikiEnvVariable) -> Binding<String> {
        Binding(
            get: {
                if cleared.contains(variable.name) { return variable.defaultValue }
                return draft[variable.name] ?? variable.currentValue
            },
            set: { value in
                cleared.remove(variable.name)
                draft[variable.name] = value
                validationErrors[variable.name] = nil
            }
        )
    }

    private func boolBinding(_ variable: WikiEnvVariable) -> Binding<Bool> {
        Binding(
            get: {
                let raw = cleared.contains(variable.name)
                    ? variable.defaultValue
                    : (draft[variable.name] ?? variable.currentValue)
                return boolValue(raw)
            },
            set: { value in
                cleared.remove(variable.name)
                draft[variable.name] = value ? "true" : "false"
                validationErrors[variable.name] = nil
            }
        )
    }

    private func boolValue(_ text: String) -> Bool {
        switch text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "true", "1", "yes", "on": return true
        default: return false
        }
    }

    private func reset(_ variable: WikiEnvVariable) {
        draft.removeValue(forKey: variable.name)
        cleared.insert(variable.name)
        validationErrors[variable.name] = nil
    }

    private func load() async {
        guard let service = app.wikiEnv else {
            isLoading = false
            return
        }
        isLoading = config == nil
        defer { isLoading = false }

        do {
            let loaded = try await service.config()
            config = loaded
            draft = [:]
            cleared = []
            validationErrors = [:]
            restart = loaded.restartSupported
            errorMessage = nil
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func apply() async {
        guard let service = app.wikiEnv, let config else { return }

        validationErrors = [:]
        var values: [String: String?] = [:]

        for variable in config.variables where isChanged(variable) {
            if cleared.contains(variable.name) {
                // `subscript = nil` would remove the key; we need an explicit
                // JSON null so the server clears the override.
                values.updateValue(nil, forKey: variable.name)
                continue
            }
            guard let value = draft[variable.name] else { continue }

            switch variable.kind {
            case "int":
                guard let number = Int(value) else {
                    validationErrors[variable.name] = "Enter a whole number."
                    continue
                }
                if let minimum = variable.minimum, Double(number) < minimum {
                    validationErrors[variable.name] = "Minimum is \(Int(minimum))."
                    continue
                }
                if let maximum = variable.maximum, Double(number) > maximum {
                    validationErrors[variable.name] = "Maximum is \(Int(maximum))."
                    continue
                }
                values[variable.name] = value
            case "float":
                guard let number = Double(value) else {
                    validationErrors[variable.name] = "Enter a number."
                    continue
                }
                if let minimum = variable.minimum, number < minimum {
                    validationErrors[variable.name] = "Minimum is \(minimum)."
                    continue
                }
                if let maximum = variable.maximum, number > maximum {
                    validationErrors[variable.name] = "Maximum is \(maximum)."
                    continue
                }
                values[variable.name] = value
            default:
                values[variable.name] = value
            }
        }

        guard validationErrors.isEmpty else {
            errorMessage = "Fix the highlighted values before applying."
            return
        }
        guard !values.isEmpty else { return }

        isSaving = true
        errorMessage = nil
        defer { isSaving = false }

        do {
            let response = try await service.set(
                WikiEnvSetRequest(values: values, restartBackend: restart)
            )
            result = response
            draft = [:]
            cleared = []
            validationErrors = [:]
            if response.restartScheduled {
                // The server is about to reload; asking it for the new values
                // now would just race the restart.
                errorMessage = nil
            } else {
                await load()
            }
            if !response.invalid.isEmpty {
                errorMessage = "The server rejected \(response.invalid.count) value(s)."
            }
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
