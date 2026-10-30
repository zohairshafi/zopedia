import SwiftUI

struct SettingsView: View {
    @Environment(AppEnvironment.self) private var app

    var body: some View {
        NavigationStack {
            List {
                Section("Account") {
                    LabeledContent("Server", value: app.serverURL ?? "—")
                    LabeledContent("User", value: app.subject ?? "—")
                    if let model = app.health?.llmModel, !model.isEmpty {
                        LabeledContent("Model", value: model)
                    }
                    Button("Disconnect", role: .destructive) {
                        Task { await app.disconnect() }
                    }
                }

                if app.canManageAdvanced {
                    Section("Advanced") {
                        NavigationLink {
                            MaintenanceSchedulesView()
                        } label: {
                            Label("Maintenance schedules", systemImage: "wrench.and.screwdriver")
                        }

                        NavigationLink {
                            WikiEnvView()
                        } label: {
                            Label("Wiki behaviour", systemImage: "slider.horizontal.3")
                        }
                    }
                }

                Section("About") {
                    LabeledContent("Version", value: version)
                    LabeledContent("Builder", value: "Zopedia")
                }
            }
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle("Settings")
        }
    }

    private var version: String {
        let short = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"
        return "\(short) (\(build))"
    }
}
