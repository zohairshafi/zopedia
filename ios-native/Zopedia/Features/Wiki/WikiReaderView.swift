import MarkdownUI
import SwiftUI
import ZopediaKit

struct WikiReaderView: View {
    @Environment(AppEnvironment.self) private var app

    let path: String
    let onOpenPage: (String) -> Void

    @State private var content: String?
    @State private var isLoading = true
    @State private var errorMessage: String?

    var body: some View {
        Group {
            if let content {
                ScrollView {
                    Markdown(
                        WikiLinkPreprocessor.preprocess(
                            WikiLinkPreprocessor.stripFrontmatter(content)
                        )
                    )
                    .markdownTheme(.zopedia)
                    .padding()
                }
                .background(ZTheme.background)
            } else if isLoading {
                ProgressView()
            } else if let errorMessage {
                ContentUnavailableView(
                    "Could not load page",
                    systemImage: "exclamationmark.triangle",
                    description: Text(errorMessage)
                )
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .environment(\.openURL, OpenURLAction { url in
            if let page = WikiLinkPreprocessor.pagePath(from: url) {
                onOpenPage(page)
                return .handled
            }
            return .systemAction
        })
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await load() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .accessibilityLabel("Reload page")
            }
        }
        .task { await load() }
    }

    private var title: String {
        (path as NSString).lastPathComponent
            .replacingOccurrences(of: ".md", with: "")
    }

    private func load() async {
        guard let wiki = app.wiki else {
            isLoading = false
            return
        }
        isLoading = content == nil
        defer { isLoading = false }

        do {
            content = try await wiki.page(path: path)
            errorMessage = nil
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}
