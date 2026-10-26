import SwiftUI
import ZopediaKit

struct WikiPageRef: Hashable {
    let path: String
}

struct WikiHomeView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.horizontalSizeClass) private var sizeClass

    private enum Mode: String, CaseIterable, Identifiable {
        case browse = "Browse"
        case search = "Search"

        var id: String { rawValue }
    }

    @State private var mode: Mode = .browse
    @State private var path = NavigationPath()
    @State private var selection: WikiPageRef?
    @State private var files: WikiFilesResponse?
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var filter = ""
    @State private var sortRecent = false
    @State private var showUpload = false

    var body: some View {
        Group {
            if sizeClass == .regular {
                NavigationSplitView {
                    sidebar(selectionMode: true)
                } detail: {
                    if let selection {
                        WikiReaderView(path: selection.path) { page in
                            self.selection = WikiPageRef(path: page)
                        }
                        .id(selection.path)
                    } else {
                        ContentUnavailableView(
                            "Select a page",
                            systemImage: "books.vertical",
                            description: Text("Choose a wiki page from the sidebar.")
                        )
                    }
                }
            } else {
                NavigationStack(path: $path) {
                    sidebar(selectionMode: false)
                        .navigationDestination(for: WikiPageRef.self) { ref in
                            WikiReaderView(path: ref.path) { page in
                                path.append(WikiPageRef(path: page))
                            }
                        }
                }
            }
        }
    }

    @ViewBuilder
    private func sidebar(selectionMode: Bool) -> some View {
        VStack(spacing: 0) {
            Picker("Mode", selection: $mode) {
                ForEach(Mode.allCases) { mode in
                    Text(mode.rawValue).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal)
            .padding(.bottom, 8)

            if let errorMessage {
                Text(errorMessage)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .padding(.bottom, 6)
            }

            switch mode {
            case .browse:
                browseView(selectionMode: selectionMode)
            case .search:
                WikiSearchView { page in
                    open(page, selectionMode: selectionMode)
                }
            }
        }
        .navigationTitle("Wiki")
        .toolbar { wikiToolbar }
        .sheet(isPresented: $showUpload) {
            WikiUploadView {
                await load()
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func browseView(selectionMode: Bool) -> some View {
        if isLoading && files == nil {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let files, files.totalCount == 0 {
            ContentUnavailableView(
                "No wiki pages",
                systemImage: "books.vertical",
                description: Text("Upload files or ingest a URL to get started.")
            )
        } else if let files {
            Group {
                if selectionMode {
                    List(selection: $selection) {
                        browseRows(selectionMode: true, files: files)
                    }
                } else {
                    List {
                        browseRows(selectionMode: false, files: files)
                    }
                }
            }
            .listStyle(.insetGrouped)
            .searchable(text: $filter, prompt: "Filter pages")
            .refreshable { await load() }
        }
    }

    @ViewBuilder
    private func browseRows(selectionMode: Bool, files: WikiFilesResponse) -> some View {
        ForEach(orderedDirectories(in: files), id: \.self) { name in
            if let directory = files.directories[name] {
                let entries = filtered(directory.files)
                if !entries.isEmpty {
                    Section(name.capitalized) {
                        ForEach(entries) { entry in
                            pageRow(entry, selectionMode: selectionMode)
                        }
                    }
                }
            }
        }

        let roots = filtered(files.rootFiles)
        if !roots.isEmpty {
            Section("Root") {
                ForEach(roots) { entry in
                    pageRow(entry, selectionMode: selectionMode)
                }
            }
        }
    }

    @ViewBuilder
    private func pageRow(_ entry: WikiFileEntry, selectionMode: Bool) -> some View {
        let ref = WikiPageRef(path: entry.relativePath)
        if selectionMode {
            WikiRow(entry: entry)
                .tag(ref)
        } else {
            NavigationLink(value: ref) {
                WikiRow(entry: entry)
            }
        }
    }

    @ToolbarContentBuilder
    private var wikiToolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Menu {
                Picker("Sort", selection: $sortRecent) {
                    Text("Name").tag(false)
                    Text("Recent").tag(true)
                }
            } label: {
                Image(systemName: "arrow.up.arrow.down")
            }
            .accessibilityLabel("Sort pages")
        }
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                showUpload = true
            } label: {
                Image(systemName: "square.and.arrow.up")
            }
            .disabled(app.permissions?.canUploadFiles == false)
            .accessibilityLabel("Add to wiki")
        }
    }

    private func orderedDirectories(in files: WikiFilesResponse) -> [String] {
        let preferred = ["entities", "concepts", "godnodes", "analysis", "sources"]

        return files.directories.keys
            .filter { !(files.directories[$0]?.files.isEmpty ?? true) }
            .sorted { lhs, rhs in
                let left = preferred.firstIndex(of: lhs.lowercased()) ?? preferred.count
                let right = preferred.firstIndex(of: rhs.lowercased()) ?? preferred.count
                if left != right { return left < right }
                return lhs.localizedCaseInsensitiveCompare(rhs) == .orderedAscending
            }
    }

    private func filtered(_ entries: [WikiFileEntry]) -> [WikiFileEntry] {
        let query = filter.trimmingCharacters(in: .whitespacesAndNewlines)
        var result = entries

        if !query.isEmpty {
            result = result.filter {
                $0.name.localizedCaseInsensitiveContains(query)
                    || $0.relativePath.localizedCaseInsensitiveContains(query)
                    || $0.preview.localizedCaseInsensitiveContains(query)
            }
        }

        if sortRecent {
            result.sort { $0.modifiedDate > $1.modifiedDate }
        } else {
            result.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        }
        return result
    }

    private func open(_ page: String, selectionMode: Bool) {
        let ref = WikiPageRef(path: page)
        if selectionMode {
            selection = ref
        } else {
            path.append(ref)
        }
    }

    private func load() async {
        guard let wiki = app.wiki else {
            isLoading = false
            return
        }
        isLoading = files == nil
        defer { isLoading = false }

        do {
            files = try await wiki.files()
            errorMessage = nil
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription
                ?? error.localizedDescription
        }
    }
}

private struct WikiRow: View {
    let entry: WikiFileEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(entry.name)
                .lineLimit(1)

            if !entry.preview.isEmpty {
                Text(entry.preview)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            HStack(spacing: 6) {
                Text(entry.relativePath)
                    .lineLimit(1)
                Text("·")
                Text(entry.modifiedDate, format: .dateTime.year().month().day())
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 2)
    }
}

extension String {
    var trimmed: String {
        trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
