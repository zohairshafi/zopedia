import SwiftUI
import UniformTypeIdentifiers
import ZopediaKit

struct WikiUploadView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppEnvironment.self) private var app

    let onUploaded: () async -> Void

    @State private var showFileImporter = false
    @State private var isUploading = false
    @State private var results: [UploadResult] = []
    @State private var errorMessage: String?
    @State private var urlText = ""

    private struct UploadResult: Identifiable {
        let id = UUID()
        let name: String
        let message: String
        let success: Bool
    }

    private var canUpload: Bool {
        app.permissions?.canUploadFiles ?? true
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
                    .disabled(isUploading || !canUpload)
                    .overlay {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .strokeBorder(
                                ZTheme.border,
                                style: StrokeStyle(lineWidth: 2, dash: [6])
                            )
                    }
                }

                Section("or ingest a URL") {
                    TextField("https://…", text: $urlText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    Button {
                        Task { await ingestURL() }
                    } label: {
                        Label("Ingest", systemImage: "link")
                    }
                    .disabled(urlText.trimmed.isEmpty || isUploading || !canUpload)
                }

                if isUploading {
                    Section {
                        ProgressView()
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(ZTheme.destructive)
                    }
                }

                if !results.isEmpty {
                    Section("Results") {
                        ForEach(results) { result in
                            HStack(alignment: .top, spacing: 8) {
                                Image(systemName: result.success
                                    ? "checkmark.circle.fill"
                                    : "xmark.circle")
                                    .foregroundStyle(result.success ? ZTheme.primary : ZTheme.destructive)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(result.name)
                                        .font(.callout)
                                        .foregroundStyle(ZTheme.foreground)
                                    Text(result.message)
                                        .font(.caption)
                                        .foregroundStyle(ZTheme.mutedForeground)
                                }
                            }
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
            .navigationTitle("Upload to wiki")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .fileImporter(
                isPresented: $showFileImporter,
                allowedContentTypes: [.item],
                allowsMultipleSelection: true
            ) { result in
                switch result {
                case .success(let urls):
                    Task { await upload(urls) }
                case .failure(let error):
                    errorMessage = error.localizedDescription
                }
            }
        }
    }

    private func upload(_ urls: [URL]) async {
        guard canUpload else {
            errorMessage = "This account does not have permission to upload files."
            return
        }
        guard let attachments = app.attachments else {
            errorMessage = "Not connected to a server."
            return
        }

        isUploading = true
        errorMessage = nil
        results = []
        defer { isUploading = false }

        var files: [UploadFile] = []
        for url in urls {
            let accessing = url.startAccessingSecurityScopedResource()
            defer { if accessing { url.stopAccessingSecurityScopedResource() } }

            do {
                let data = try Data(contentsOf: url)
                files.append(UploadFile(
                    name: url.lastPathComponent,
                    mimeType: mimeType(for: url),
                    data: data
                ))
            } catch {
                results.append(UploadResult(
                    name: url.lastPathComponent,
                    message: error.localizedDescription,
                    success: false
                ))
            }
        }

        guard !files.isEmpty else { return }

        do {
            let response = try await attachments.uploadFiles(files)
            results.append(contentsOf: response.uploaded.map {
                UploadResult(name: $0, message: "Uploaded", success: true)
            })
            results.append(contentsOf: response.failed.map {
                UploadResult(name: $0.filename, message: $0.reason, success: false)
            })
            await onUploaded()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func ingestURL() async {
        guard canUpload else {
            errorMessage = "This account does not have permission to upload files."
            return
        }
        guard let wiki = app.wiki else { return }
        let value = urlText.trimmed
        guard value.lowercased().hasPrefix("http://")
                || value.lowercased().hasPrefix("https://") else {
            errorMessage = "Enter an http:// or https:// URL."
            return
        }

        isUploading = true
        errorMessage = nil
        defer { isUploading = false }

        do {
            let response = try await wiki.ingest(url: value)
            if response.status == "already_ingested" {
                results.append(UploadResult(
                    name: value,
                    message: "Already ingested.",
                    success: true
                ))
            } else {
                results.append(UploadResult(
                    name: value,
                    message: "Ingested \(response.processedFiles) item(s).",
                    success: true
                ))
            }
            urlText = ""
            await onUploaded()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func mimeType(for url: URL) -> String {
        UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
            ?? "application/octet-stream"
    }
}
