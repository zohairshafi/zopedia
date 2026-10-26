import MarkdownUI
import SwiftUI
import ZopediaKit

struct WikiSearchView: View {
    @Environment(AppEnvironment.self) private var app

    let onOpen: (String) -> Void

    @State private var question = ""
    @State private var result: WikiQueryResponse?
    @State private var isSearching = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 12) {
            HStack(alignment: .bottom) {
                TextField("Ask the wiki", text: $question, axis: .vertical)
                    .lineLimit(1...3)
                    .textFieldStyle(.roundedBorder)

                Button("Search") {
                    Task { await search() }
                }
                .disabled(question.trimmed.isEmpty || isSearching)
            }
            .padding(.horizontal)

            if isSearching {
                ProgressView("Searching…")
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
            }

            if let result {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        Markdown(result.answer)
                            .textSelection(.enabled)

                        if !result.contextPages.isEmpty {
                            Text("Sources")
                                .font(.headline)

                            ForEach(result.contextPages, id: \.self) { page in
                                Button {
                                    onOpen(page)
                                } label: {
                                    HStack {
                                        Image(systemName: "doc.text")
                                        Text(page)
                                            .lineLimit(1)
                                        Spacer()
                                        Image(systemName: "chevron.right")
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                                .buttonStyle(.plain)
                                .padding(.vertical, 2)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding()
                }
            } else if !isSearching {
                ContentUnavailableView(
                    "Search the wiki",
                    systemImage: "magnifyingglass",
                    description: Text("Ask a question and the wiki will answer from its pages.")
                )
            }
        }
        .padding(.top, 8)
    }

    private func search() async {
        let query = question.trimmed
        guard !query.isEmpty, let wiki = app.wiki else { return }

        isSearching = true
        errorMessage = nil
        defer { isSearching = false }

        do {
            result = try await wiki.query(question: query)
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}
