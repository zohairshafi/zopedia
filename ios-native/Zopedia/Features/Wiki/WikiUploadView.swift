import SwiftUI
import UniformTypeIdentifiers
import ZopediaKit

struct WikiUploadView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppEnvironment.self) private var app

    let onUploaded: () async -> Void

    @State private var showFileImporter = false
    @State private var isUploading = false
    @State private var results: [String] = []
    @State private var errorMessage: String?
    @State private var urlText = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Files") {
                    Button("Choose files") {
                        showFileImporter = true
                    }
                    .disabled(isUploading)

                    Text("Markdown, text, PDF, Office, HTML, CSV, EPUB, images, audio, or zip.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Ingest a URL") {
                    TextField("https://…", text: $urlText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    Button("Ingest") {
                        Task { await ingestURL() }
                    }
                    .disabled(urlText.trimmed.isEmpty || isUploading)
                }

                if isUploading {
                    Section {
                        ProgressView()
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(.red)
                    }
                }

                if !results.isEmpty {
                    Section("Results") {
                        ForEach(results, id: \.self) { result in
                            Text(result)
                                .font(.callout)
                        }
                    }
                }
            }
            .navigationTitle("Add to wiki")
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
                results.append("\(url.lastPathComponent): \(error.localizedDescription)")
            }
        }

        guard !files.isEmpty else { return }

        do {
            let response = try await attachments.uploadFiles(files)
            results.append(contentsOf: response.uploaded.map { "Uploaded \($0)" })
            results.append(contentsOf: response.failed.map {
                "\($0.filename): \($0.reason)"
            })
            await onUploaded()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func ingestURL() async {
        guard let wiki = app.wiki else { return }
        let value = urlText.trimmed
        guard value.lowercased().hasPrefix("http://")
                || value.lowercased().hasPrefix("https://") else {
            errorMessage = "Enter an http:// or https:// URL."
            return
        }

        isUploading = true
        errorMessage = nil
        results = []
        defer { isUploading = false }

        do {
            let response = try await wiki.ingest(url: value)
            if response.status == "already_ingested" {
                results.append("Already ingested.")
            } else {
                results.append("Ingested \(response.processedFiles) item(s).")
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
