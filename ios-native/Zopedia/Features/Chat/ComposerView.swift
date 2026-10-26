import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import ZopediaKit

struct ComposerView: View {
    @Environment(AppEnvironment.self) private var app
    @Bindable var model: ChatViewModel

    @State private var photoItem: PhotosPickerItem?
    @State private var showPhotoPicker = false
    @State private var showFileImporter = false
    @State private var attachedImage: PreparedImage?
    @State private var imagePreview: UIImage?
    @State private var pdfText: String?
    @State private var pdfName: String?
    @State private var pendingPDF: PendingPDF?
    @State private var showPDFChoice = false
    @State private var isPreparing = false
    @State private var attachmentError: String?
    @State private var attachmentInfo: String?

    private struct PendingPDF {
        let data: Data
        let name: String
    }

    private var hasAttachment: Bool {
        attachedImage != nil || pdfText != nil
    }

    private var canSend: Bool {
        !model.isStreaming && !isPreparing
            && (!model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || hasAttachment)
    }

    var body: some View {
        VStack(spacing: 6) {
            if model.isStreaming, let status = model.toolStatus, !status.isEmpty {
                Text(status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
            }

            if hasAttachment || attachmentError != nil || attachmentInfo != nil || isPreparing {
                attachmentRow
            }

            HStack(alignment: .bottom, spacing: 8) {
                Menu {
                    Button {
                        showPhotoPicker = true
                    } label: {
                        Label("Photo", systemImage: "photo")
                    }
                    Button {
                        showFileImporter = true
                    } label: {
                        Label("PDF", systemImage: "doc")
                    }
                } label: {
                    Image(systemName: "paperclip")
                        .font(.title3)
                        .frame(width: 34, height: 34)
                }
                .disabled(model.isStreaming || isPreparing)
                .accessibilityLabel("Add attachment")

                TextField("Message", text: $model.draft, axis: .vertical)
                    .lineLimit(1...6)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                    .background(
                        Color.secondary.opacity(0.10),
                        in: RoundedRectangle(cornerRadius: 18, style: .continuous)
                    )
                    .disabled(model.isStreaming)

                if model.isStreaming {
                    Button("Stop") { model.stopWaiting() }
                        .buttonStyle(.bordered)
                } else {
                    Button(action: send) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title2)
                    }
                    .disabled(!canSend)
                    .accessibilityLabel("Send")
                }
            }
            .padding(.horizontal)
        }
        .padding(.vertical, 8)
        .background(.bar)
        .photosPicker(isPresented: $showPhotoPicker, selection: $photoItem, matching: .images)
        .onChange(of: photoItem) { _, item in
            Task { await loadPhoto(item) }
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.pdf]
        ) { result in
            switch result {
            case .success(let url):
                loadPDF(url)
            case .failure(let error):
                attachmentError = error.localizedDescription
            }
        }
        .confirmationDialog(
            "PDF selected",
            isPresented: $showPDFChoice,
            presenting: pendingPDF
        ) { pdf in
            Button("Use in this conversation") {
                Task { await extract(pdf) }
            }
            Button("Add to wiki") {
                Task { await ingest(pdf) }
            }
            Button("Cancel", role: .cancel) {
                pendingPDF = nil
            }
        } message: { pdf in
            Text(pdf.name)
        }
    }

    private var attachmentRow: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let attachmentError {
                Text(attachmentError)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else if let attachmentInfo {
                Text(attachmentInfo)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 10) {
                if let imagePreview {
                    ZStack(alignment: .topTrailing) {
                        Image(uiImage: imagePreview)
                            .resizable()
                            .scaledToFill()
                            .frame(width: 56, height: 56)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                        Button {
                            attachedImage = nil
                            self.imagePreview = nil
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.white, .black.opacity(0.6))
                        }
                        .offset(x: 6, y: -6)
                        .accessibilityLabel("Remove image")
                    }
                }

                if let pdfName {
                    HStack(spacing: 6) {
                        Image(systemName: "doc.text")
                        Text(pdfName)
                            .lineLimit(1)
                        if let pdfText {
                            Text("\(pdfText.count) chars")
                                .foregroundStyle(.secondary)
                        }
                        Button {
                            pdfText = nil
                            self.pdfName = nil
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                        }
                        .accessibilityLabel("Remove PDF")
                    }
                    .font(.caption)
                    .padding(8)
                    .background(
                        Color.secondary.opacity(0.1),
                        in: RoundedRectangle(cornerRadius: 8)
                    )
                }

                if isPreparing {
                    ProgressView()
                }
                Spacer()
            }
        }
        .padding(.horizontal)
    }

    private func loadPhoto(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        isPreparing = true
        attachmentError = nil
        attachmentInfo = nil
        defer { isPreparing = false }

        do {
            guard let data = try await item.loadTransferable(type: Data.self) else {
                throw AttachmentProcessingError.unreadable
            }
            let prepared = try AttachmentProcessor.prepareImage(from: data)
            attachedImage = prepared
            imagePreview = UIImage(data: prepared.jpegData)
            pdfText = nil
            pdfName = nil
        } catch {
            attachmentError = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
        photoItem = nil
    }

    private func loadPDF(_ url: URL) {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }

        do {
            let data = try Data(contentsOf: url)
            pendingPDF = PendingPDF(data: data, name: url.lastPathComponent)
            showPDFChoice = true
            attachmentError = nil
        } catch {
            attachmentError = "Could not read the PDF: \(error.localizedDescription)"
        }
    }

    private func extract(_ pdf: PendingPDF) async {
        guard let attachments = app.attachments else {
            attachmentError = "Not connected to a server."
            return
        }
        isPreparing = true
        attachmentError = nil
        attachmentInfo = nil
        defer {
            isPreparing = false
            pendingPDF = nil
        }

        do {
            let result = try await attachments.extractPDF(data: pdf.data, filename: pdf.name)
            pdfText = result.text
            pdfName = result.name
            attachedImage = nil
            imagePreview = nil
            if result.truncated {
                attachmentInfo = "The PDF was truncated to 100,000 characters."
            }
        } catch {
            attachmentError = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func ingest(_ pdf: PendingPDF) async {
        guard let attachments = app.attachments else {
            attachmentError = "Not connected to a server."
            return
        }
        isPreparing = true
        attachmentError = nil
        attachmentInfo = nil
        defer {
            isPreparing = false
            pendingPDF = nil
        }

        do {
            let result = try await attachments.uploadFiles([
                UploadFile(name: pdf.name, mimeType: "application/pdf", data: pdf.data),
            ])
            if result.failed.isEmpty {
                attachmentInfo = "Added \(pdf.name) to the wiki."
            } else {
                attachmentError = result.failed
                    .map { "\($0.filename): \($0.reason)" }
                    .joined(separator: "\n")
            }
        } catch {
            attachmentError = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func send() {
        let image = attachedImage
        let pdf = pdfText
        let name = pdfName

        Task {
            await model.send(
                imageBase64: image?.base64,
                imageData: image?.jpegData,
                imageName: image?.fileName,
                extractedText: pdf,
                attachmentName: name
            )
        }

        attachedImage = nil
        imagePreview = nil
        pdfText = nil
        pdfName = nil
        attachmentError = nil
        attachmentInfo = nil
    }
}
