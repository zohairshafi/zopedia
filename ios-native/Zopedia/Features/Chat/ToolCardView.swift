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

    private var appearance: ToolAppearance {
        ToolPresentation.appearance(for: tool.toolName)
    }

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
        card {
            Text(question)
                .font(.callout)
                .foregroundStyle(ZTheme.foreground)

            if isComplete || submitted {
                Text(askOutcome)
                    .font(.caption)
                    .foregroundStyle(ZTheme.mutedForeground)
            } else {
                ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                    Button(option) { submit(option) }
                        .buttonStyle(.bordered)
                        .tint(ZTheme.primary)
                }
                HStack {
                    TextField("Type an answer", text: $freeText)
                        .textFieldStyle(.roundedBorder)
                    Button("Send") { submit(freeText) }
                        .buttonStyle(.borderedProminent)
                        .tint(ZTheme.primary)
                        .disabled(freeText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
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
        card {
            Text(orderSummary)
                .font(.headline)
                .foregroundStyle(ZTheme.foreground)

            if let rationale = args["rationale"]?.stringValue, !rationale.isEmpty {
                Text(rationale)
                    .font(.callout)
                    .foregroundStyle(ZTheme.mutedForeground)
            }

            if args["market_open"]?.boolValue == false {
                Text("The market is closed. The order would queue for the next open.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            if isComplete || decided {
                Text(tradeOutcome)
                    .font(.caption)
                    .foregroundStyle(ZTheme.mutedForeground)
            } else {
                HStack {
                    Button("Approve") { decide(true) }
                        .buttonStyle(.borderedProminent)
                        .tint(ZTheme.primary)
                    Button("Reject", role: .destructive) { decide(false) }
                        .buttonStyle(.bordered)
                }
            }
        }
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
        card {
            if let sql = sqlResult {
                SQLResultTable(result: sql)
            }

            DisclosureGroup {
                VStack(alignment: .leading, spacing: 8) {
                    if let query = args["query"]?.stringValue, !query.isEmpty {
                        Text(query)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(ZTheme.mutedForeground)
                            .textSelection(.enabled)
                    }
                    if let value = tool.args, !value.prettyPrinted.isEmpty {
                        Text(value.prettyPrinted)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(ZTheme.mutedForeground)
                            .textSelection(.enabled)
                    }
                    if let result = tool.result, !result.isEmpty {
                        Divider().overlay(ZTheme.border)
                        Text(result)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(ZTheme.mutedForeground)
                            .textSelection(.enabled)
                            .lineLimit(20)
                    }
                }
                .padding(.top, 6)
            } label: {
                Text("Details")
                    .font(.caption)
                    .foregroundStyle(ZTheme.mutedForeground)
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
        }
    }

    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: appearance.icon)
                Text(appearance.title)
                    .font(.caption.weight(.medium))
                Spacer()
                statusBadge
            }
            .foregroundStyle(ZTheme.mutedForeground)

            content()
        }
        .padding(12)
        .background(ZTheme.muted, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(ZTheme.border, lineWidth: 1)
        }
    }

    @ViewBuilder
    private var statusBadge: some View {
        if isComplete {
            if ToolPresentation.resultFailed(tool.result) {
                Image(systemName: "xmark.circle")
                    .foregroundStyle(ZTheme.destructive)
            } else {
                Image(systemName: "checkmark.square")
                    .foregroundStyle(ZTheme.primary)
            }
        } else {
            ProgressView()
                .controlSize(.mini)
        }
    }

    // MARK: - SQL result

    fileprivate struct SQLResult {
        let columns: [String]
        let rows: [[String: JSONValue]]
        let rowCount: Int
        let truncated: Bool
    }

    private var sqlResult: SQLResult? {
        guard tool.toolName == "execute_sql_query",
              let result = tool.result,
              let data = result.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let columns = object["columns"] as? [String],
              let rawRows = object["rows"] as? [[String: Any]] else {
            return nil
        }

        let rows = rawRows.map { rawRow in
            var converted: [String: JSONValue] = [:]
            for (key, value) in rawRow {
                if let json = try? JSONValue(any: value) {
                    converted[key] = json
                }
            }
            return converted
        }

        return SQLResult(
            columns: columns,
            rows: rows,
            rowCount: object["row_count"] as? Int ?? rows.count,
            truncated: object["truncated"] as? Bool ?? false
        )
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

private struct SQLResultTable: View {
    let result: ToolCardView.SQLResult

    var body: some View {
        VStack(spacing: 0) {
            ScrollView(.horizontal, showsIndicators: true) {
                Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
                    GridRow {
                        ForEach(result.columns, id: \.self) { column in
                            cell(Text(column).fontWeight(.semibold), header: true)
                        }
                    }

                    ForEach(Array(result.rows.enumerated()), id: \.offset) { _, row in
                        GridRow {
                            ForEach(result.columns, id: \.self) { column in
                                cell(valueText(row[column]), header: false)
                            }
                        }
                    }
                }
            }

            HStack {
                Text("\(result.rowCount) row\(result.rowCount == 1 ? "" : "s")\(result.truncated ? " (truncated)" : "")")
                Spacer()
            }
            .font(.caption2)
            .foregroundStyle(ZTheme.mutedForeground)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(ZTheme.muted)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(ZTheme.border, lineWidth: 1)
        }
    }

    private func cell(_ text: Text, header: Bool) -> some View {
        text
            .font(.caption2)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .frame(minWidth: 70, maxWidth: 220, alignment: .leading)
            .background(header ? ZTheme.muted : Color.clear)
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(ZTheme.border)
                    .frame(height: 1)
            }
    }

    private func valueText(_ value: JSONValue?) -> Text {
        guard let value else {
            return Text("NULL").italic().foregroundColor(ZTheme.mutedForeground)
        }
        switch value {
        case .null:
            return Text("NULL").italic().foregroundColor(ZTheme.mutedForeground)
        case .string(let text):
            return Text(text)
        case .int(let number):
            return Text(String(number))
        case .double(let number):
            return Text(String(number))
        case .bool(let flag):
            return Text(flag ? "true" : "false")
        case .array, .object:
            return Text(value.prettyPrinted)
        }
    }
}
