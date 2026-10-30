import SwiftUI
import UniformTypeIdentifiers
import ZopediaKit

struct WikiUploadView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppEnvironment.self) private var app

    @State private var showFileImporter = false
    @State private var pendingFiles: [PendingUpload] = []
    @State private var preparingCount = 0
    @State private var errorMessage: String?
    @State private var urlText = ""

    private struct PendingUpload: Identifiable {
        let id = UUID()
        let name: String
        let mimeType: String
        let data: Data

        var uploadFile: UploadFile {
            UploadFile(name: name, mimeType: mimeType, data: data)
        }
    }

    private struct PreparedFile: Sendable {
        let name: String
        let mimeType: String
        let data: Data
    }

    private var canUpload: Bool {
        app.permissions?.canUploadFiles ?? true
    }

    private var trimmedURL: String {
        urlText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var canSubmit: Bool {
        canUpload
            && preparingCount == 0
            && (!pendingFiles.isEmpty || !trimmedURL.isEmpty)
    }

    var body: some View {
        NavigationStack {
            Form {
                if !canUpload {
                    Section {
                        Text("This account does not have permission to upload files.")
                            .font(.callout)
                            .foregroundStyle(ZTheme.destructive)
                    }
                }

                Section("Files") {
                    Button {
                        showFileImporter = true
                    } label: {
                        VStack(spacing: 8) {
                            Image(systemName: "arrow.up.doc")
                                .font(.title2)
                                .foregroundStyle(ZTheme.primary)
                            Text("Choose files")
                                .font(.headline)
                                .foregroundStyle(ZTheme.foreground)
                            Text("Markdown, text, PDF, Office, HTML, CSV, EPUB, images, audio, or zip.")
                                .font(.caption)
                                .foregroundStyle(ZTheme.mutedForeground)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 20)
                    }
                    .buttonStyle(.plain)
                    .disabled(preparingCount > 0 || !canUpload)
                    .overlay {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .strokeBorder(
                                ZTheme.border,
                                style: StrokeStyle(lineWidth: 2, dash: [6])
                            )
                    }

                    ForEach(pendingFiles) { file in
                        HStack(spacing: 10) {
                            Image(systemName: "doc")
                                .foregroundStyle(ZTheme.mutedForeground)
                            Text(file.name)
                                .font(.callout)
                                .foregroundStyle(ZTheme.foreground)
                                .lineLimit(1)
                            Spacer()
                            Button {
                                pendingFiles.removeAll { $0.id == file.id }
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(ZTheme.mutedForeground)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Remove \(file.name)")
                        }
                    }

                    if preparingCount > 0 {
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Preparing files…")
                                .font(.callout)
                                .foregroundStyle(ZTheme.mutedForeground)
                        }
                    }
                }

                Section("or add a URL") {
                    TextField("https://…", text: $urlText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(ZTheme.destructive)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle("Add to wiki")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add to Wiki") {
                        submit()
                    }
                    .disabled(!canSubmit)
                }
            }
            .fileImporter(
                isPresented: $showFileImporter,
                allowedContentTypes: [.item],
                allowsMultipleSelection: true
            ) { result in
                switch result {
                case .success(let urls):
                    prepare(urls)
                case .failure(let error):
                    errorMessage = error.localizedDescription
                }
            }
        }
    }

    private func prepare(_ urls: [URL]) {
        guard canUpload else {
            errorMessage = "This account does not have permission to upload files."
            return
        }
        errorMessage = nil
        preparingCount += 1

        Task {
            let loaded = await Task.detached(priority: .userInitiated) { () -> ([PreparedFile], [String]) in
                var files: [PreparedFile] = []
                var failures: [String] = []

                for url in urls {
                    let accessing = url.startAccessingSecurityScopedResource()
                    defer { if accessing { url.stopAccessingSecurityScopedResource() } }

                    do {
                        let data = try Data(contentsOf: url)
                        files.append(PreparedFile(
                            name: url.lastPathComponent,
                            mimeType: UTType(filenameExtension: url.pathExtension)?
                                .preferredMIMEType ?? "application/octet-stream",
                            data: data
                        ))
                    } catch {
                        failures.append("\(url.lastPathComponent): \(error.localizedDescription)")
                    }
                }
                return (files, failures)
            }.value

            pendingFiles.append(contentsOf: loaded.0.map {
                PendingUpload(name: $0.name, mimeType: $0.mimeType, data: $0.data)
            })
            if !loaded.1.isEmpty {
                errorMessage = loaded.1.joined(separator: "\n")
            }
            preparingCount -= 1
        }
    }

    private func submit() {
        guard canUpload else {
            errorMessage = "This account does not have permission to upload files."
            return
        }

        let url = trimmedURL
        if !url.isEmpty,
           !url.lowercased().hasPrefix("http://"),
           !url.lowercased().hasPrefix("https://") {
            errorMessage = "Enter an http:// or https:// URL."
            return
        }

        guard !pendingFiles.isEmpty || !url.isEmpty else { return }
        guard app.attachments != nil, app.wiki != nil else {
            errorMessage = "Not connected to a server."
            return
        }

        let files = pendingFiles.map(\.uploadFile)
        dismiss()
        app.wikiUploads.submit(
            files: files,
            url: url.isEmpty ? nil : url,
            attachments: app.attachments,
            wiki: app.wiki
        )
    }
}
