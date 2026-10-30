import Foundation
import Observation
import ZopediaKit

/// Runs wiki uploads after the sheet closes so adding files or a URL never
/// blocks the UI. The Wiki tab observes this to refresh and report failures.
@MainActor
@Observable
final class WikiUploadMonitor {
    private(set) var activeCount = 0
    private(set) var completionID = 0
    private(set) var errorMessage: String?
    private(set) var lastMessage: String?

    var isWorking: Bool { activeCount > 0 }

    func submit(
        files: [UploadFile],
        url: String?,
        attachments: AttachmentService?,
        wiki: WikiService?
    ) {
        guard !files.isEmpty || url != nil else { return }
        guard let attachments, let wiki else {
            errorMessage = "Not connected to a server."
            return
        }

        activeCount += 1
        errorMessage = nil
        lastMessage = nil

        Task {
            defer {
                activeCount -= 1
                completionID += 1
            }

            var messages: [String] = []
            var failures: [String] = []

            if !files.isEmpty {
                do {
                    let response = try await attachments.uploadFiles(files)
                    if !response.uploaded.isEmpty {
                        messages.append(
                            "Uploaded \(response.uploaded.count) file(s). Ingestion continues on the server."
                        )
                    }
                    failures.append(contentsOf: response.failed.map {
                        "\($0.filename): \($0.reason)"
                    })
                } catch {
                    failures.append(Self.message(for: error))
                }
            }

            if let url {
                do {
                    let response = try await wiki.ingest(url: url)
                    if response.status == "already_ingested" {
                        messages.append("That URL was already ingested.")
                    } else {
                        messages.append("Queued the URL. Ingestion continues on the server.")
                    }
                } catch {
                    failures.append(Self.message(for: error))
                }
            }

            lastMessage = messages.isEmpty ? nil : messages.joined(separator: " ")
            if !failures.isEmpty {
                errorMessage = failures.joined(separator: "\n")
            }
        }
    }

    func clearMessage() {
        lastMessage = nil
    }

    func clearError() {
        errorMessage = nil
    }

    private static func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
