import SwiftUI
import ZopediaKit

struct ToolCardView: View {
    let tool: ToolCallPart
    let fallbackSessionID: String
    var onAnswer: ((String, String, String) -> Void)?
    var onDecision: ((String, String, Bool) -> Void)?

    @State private var freeText = ""
    @State private var submitted = false
    @State private var decided = false

    var body: some View {
        switch tool.toolName {
        case "ask_user_question":
            askCard
        case "alpaca_trade":
            tradeCard
        default:
            genericCard
        }
    }

    // MARK: - ask_user_question

    private var question: String {
        args["question"]?.stringValue ?? "Question"
    }

    private var options: [String] {
        args["options"]?.arrayValue?.compactMap(\.stringValue) ?? []
    }

    private var askCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Question", systemImage: "questionmark.bubble")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(question)
                .font(.callout)

            if isComplete || submitted {
                Text(askOutcome)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                    Button(option) { submit(option) }
                        .buttonStyle(.bordered)
                }
                HStack {
                    TextField("Type an answer", text: $freeText)
                        .textFieldStyle(.roundedBorder)
                    Button("Send") { submit(freeText) }
                        .disabled(freeText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .padding(12)
        .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
    }

    private var askOutcome: String {
        if submitted && !isComplete {
            return "Answer sent — the assistant will continue shortly…"
        }
        if let answer = resultObject?["answer"]?.stringValue {
            return "Answered: \(answer)"
        }
        if resultObject?["answer"] == .null {
            return "The assistant continued without an answer."
        }
        return "Completed."
    }

    private func submit(_ value: String) {
        let answer = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty, !submitted else { return }
        submitted = true
        onAnswer?(sessionID, tool.toolCallID, answer)
    }

    // MARK: - alpaca_trade

    private var tradeCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Trade approval", systemImage: "chart.line.uptrend.xyaxis")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(orderSummary)
                .font(.headline)

            if let rationale = args["rationale"]?.stringValue, !rationale.isEmpty {
                Text(rationale)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            if args["market_open"]?.boolValue == false {
                Text("The market is closed. The order would queue for the next open.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            if isComplete || decided {
                Text(tradeOutcome)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                HStack {
                    Button("Approve") { decide(true) }
                        .buttonStyle(.borderedProminent)
                    Button("Reject", role: .destructive) { decide(false) }
                        .buttonStyle(.bordered)
                }
            }
        }
        .padding(12)
        .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
    }

    private var orderSummary: String {
        let order = args["order"]?.objectValue ?? [:]
        let side = order["side"]?.stringValue ?? ""
        let quantity = numberOrString(order["qty"])
        let symbol = order["symbol"]?.stringValue ?? ""
        let type = order["type"]?.stringValue ?? ""
        let parts = [side, quantity, symbol, type].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.joined(separator: " ").uppercased()
    }

    private var tradeOutcome: String {
        if decided && !isComplete {
            return "Decision sent — waiting for the server."
        }
        switch resultObject?["status"]?.stringValue {
        case "placed": return "Order placed."
        case "rejected": return "Rejected. Nothing was placed."
        case "expired": return "Expired. Nothing was placed."
        case "failed": return "The order failed."
        default: return "Completed."
        }
    }

    private func decide(_ approve: Bool) {
        guard !decided else { return }
        decided = true
        onDecision?(sessionID, tool.toolCallID, approve)
    }

    // MARK: - generic

    private var genericCard: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 8) {
                if let value = tool.args, !value.prettyPrinted.isEmpty {
                    Text(value.prettyPrinted)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                }
                if let result = tool.result, !result.isEmpty {
                    Divider()
                    Text(result)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .lineLimit(20)
                }
            }
            .padding(.top, 6)
        } label: {
            Label(tool.toolName, systemImage: "wrench.and.screwdriver")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
    }

    // MARK: - Helpers

    private var args: [String: JSONValue] {
        tool.args?.objectValue ?? [:]
    }

    private var sessionID: String {
        if let value = args["session_id"]?.stringValue, !value.isEmpty {
            return value
        }
        return fallbackSessionID
    }

    private var isComplete: Bool {
        tool.result != nil
    }

    private var resultObject: [String: JSONValue]? {
        guard let result = tool.result,
              let data = result.data(using: .utf8),
              let value = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            return nil
        }
        return value.objectValue
    }

    private func numberOrString(_ value: JSONValue?) -> String? {
        guard let value else { return nil }
        if let text = value.stringValue { return text }
        if let integer = value.intValue { return String(integer) }
        if case .double(let double) = value { return String(double) }
        return nil
    }
}
