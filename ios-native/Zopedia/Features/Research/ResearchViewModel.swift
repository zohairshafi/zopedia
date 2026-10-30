import Foundation
import Observation
import ZopediaKit

@MainActor
@Observable
final class ResearchViewModel {
    enum Phase: Equatable {
        case running
        case awaitingApproval
        case complete
        case failed
        case cancelled
    }

    private(set) var phase: Phase = .running
    private(set) var topic = ""
    private(set) var title: String?
    private(set) var currentRound = 0
    private(set) var totalRounds = 0
    private(set) var statusText = ""
    private(set) var activity: [String] = []
    private(set) var sources: [ResearchSource] = []
    private(set) var selectedURLs: Set<String> = []
    private(set) var awaitingRound: Int?
    private(set) var report = ""
    private(set) var reportIsStreaming = false
    private(set) var survey = ""
    private(set) var warnings: [ResearchWarning] = []
    private(set) var errorMessage: String?
    private(set) var completionMessage: String?

    private let app: AppEnvironment
    private var sessionID = ""
    private var streamTask: Task<Void, Never>?

    init(app: AppEnvironment) {
        self.app = app
    }

    var progress: Double {
        guard totalRounds > 0 else { return 0 }
        return min(Double(currentRound) / Double(totalRounds), 1)
    }

    var phaseLabel: String {
        switch phase {
        case .running: return "Running"
        case .awaitingApproval: return "Awaiting approval"
        case .complete: return "Complete"
        case .failed: return "Failed"
        case .cancelled: return "Cancelled"
        }
    }

    var isTerminal: Bool {
        phase == .complete || phase == .failed || phase == .cancelled
    }

    var hasReport: Bool {
        !report.isEmpty
    }

    func start(config: ResearchConfig) {
        guard let research = app.research else { return }

        streamTask?.cancel()
        sessionID = config.sessionID ?? UUID().uuidString
        topic = config.topic
        title = nil
        currentRound = 0
        totalRounds = config.rounds
        statusText = "Starting research…"
        activity = []
        sources = []
        selectedURLs = []
        awaitingRound = nil
        report = ""
        reportIsStreaming = false
        survey = ""
        warnings = []
        errorMessage = nil
        completionMessage = nil
        phase = .running

        var request = config
        request.sessionID = sessionID

        streamTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                for try await event in research.stream(config: request) {
                    self.handle(event)
                    if event == .done { break }
                }
                self.finishStream()
            } catch let error as APIError where error == .cancelled {
                if self.phase != .cancelled {
                    self.phase = .cancelled
                    self.statusText = "Cancelled."
                }
            } catch {
                self.phase = .failed
                self.errorMessage = (error as? LocalizedError)?.errorDescription
                    ?? error.localizedDescription
            }
        }
    }

    func setSourceSelected(_ url: String, selected: Bool) {
        if selected {
            selectedURLs.insert(url)
        } else {
            selectedURLs.remove(url)
        }
    }

    func approveSelected() async {
        await approve(urls: Array(selectedURLs))
    }

    func skipRound() async {
        await approve(urls: [])
    }

    func cancel() async {
        guard let research = app.research, !sessionID.isEmpty else { return }
        do {
            try await research.cancel(sessionID: sessionID)
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
            return
        }
        streamTask?.cancel()
        streamTask = nil
        phase = .cancelled
        statusText = "Cancelled."
        reportIsStreaming = false
    }

    private func approve(urls: [String]) async {
        guard let research = app.research, let round = awaitingRound else { return }
        let rejected = sources.map(\.url).filter { !urls.contains($0) }

        do {
            try await research.approve(
                sessionID: sessionID,
                approvedURLs: urls,
                rejectedURLs: rejected
            )
            activity.append("Round \(round): approved \(urls.count) source(s).")
            phase = .running
            awaitingRound = nil
            statusText = urls.isEmpty ? "Skipping this round…" : "Ingesting sources…"
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }

    private func handle(_ event: ResearchEvent) {
        switch event {
        case .started(let topic, let rounds, _, _):
            self.topic = topic
            totalRounds = rounds
            statusText = "Surveying the wiki…"

        case .survey(let content):
            survey += content
            statusText = "Survey complete."

        case .roundStarted(let round, let rounds):
            currentRound = round
            totalRounds = rounds
            sources = []
            selectedURLs = []
            statusText = "Round \(round) of \(rounds): searching…"

        case .searching:
            statusText = "Searching for sources…"

        case .sourcesFound(_, let found):
            sources = found
            selectedURLs = Set(found.filter { !$0.alreadyInWiki }.map(\.url))

        case .awaitingApproval(let round, let count):
            awaitingRound = round
            phase = .awaitingApproval
            statusText = "Approve sources for round \(round) (\(count))."

        case .ingestStart(let url):
            statusText = "Ingesting \(url)…"

        case .ingestComplete(let url, let title, let status, let error):
            let name = title.isEmpty ? url : title
            if let error, !error.isEmpty {
                activity.append("\(name): \(status) — \(error)")
            } else {
                activity.append("\(name): \(status)")
            }

        case .maintenanceStart(let step):
            statusText = "Maintenance: \(step)…"

        case .maintenanceProgress(let step, _):
            statusText = "Maintenance: \(step)…"

        case .maintenanceComplete(let steps):
            activity.append("Maintenance completed (\(steps) steps).")

        case .roundComplete(let round, let ingested, let failed, _, _):
            activity.append("Round \(round): \(ingested) ingested, \(failed) failed.")
            statusText = "Round \(round) complete."

        case .summarizing(let message):
            reportIsStreaming = true
            statusText = message.isEmpty ? "Writing the report…" : message

        case .finalSummary(let chunk):
            report += chunk

        case .warnings(let items):
            warnings.append(contentsOf: items)

        case .title(let value):
            title = value

        case .toolStatus(let text):
            if !text.isEmpty { statusText = text }

        case .toolStart(let name, _, _):
            activity.append("Tool: \(ToolPresentation.appearance(for: name).title)")

        case .toolEnd:
            break

        case .completed(let total):
            phase = .complete
            reportIsStreaming = false
            completionMessage = "Ingested \(total) source\(total == 1 ? "" : "s")."
            activity.append(completionMessage ?? "Research complete.")
            statusText = "Complete."

        case .error(let message):
            phase = .failed
            reportIsStreaming = false
            errorMessage = message

        case .cancelled(let message):
            phase = .cancelled
            reportIsStreaming = false
            statusText = message.isEmpty ? "Cancelled." : message

        case .done, .unknown:
            break
        }
    }

    private func finishStream() {
        reportIsStreaming = false
        if phase == .running || phase == .awaitingApproval {
            phase = .failed
            errorMessage = "The research stream ended without a result."
        }
    }
}
