import SwiftUI
import ZopediaKit

struct WikiPageRef: Hashable {
    let path: String
}

struct WikiHomeView: View {
    @Environment(AppEnvironment.self) private var app
    @Environment(\.horizontalSizeClass) private var sizeClass

    @Binding var pendingPath: String?

    @State private var path = NavigationPath()
    @State private var selection: WikiPageRef?
    @State private var files: WikiFilesResponse?
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var filter = ""
    @State private var sortRecent = false
    @State private var showUpload = false
    @State private var expanded: Set<String> = []

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
        .onChange(of: pendingPath) { _, value in
            openPending(value)
        }
        .onAppear {
            openPending(pendingPath)
            if files == nil {
                Task { await load() }
            }
        }
    }

    @ViewBuilder
    private func sidebar(selectionMode: Bool) -> some View {
        VStack(spacing: 0) {
            header

            if let errorMessage {
                Text(errorMessage)
                    .font(.callout)
                    .foregroundStyle(ZTheme.destructive)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .padding(.bottom, 6)
            }

            browseView(selectionMode: selectionMode)
        }
        .background(ZTheme.background)
        .navigationTitle("Wiki")
        .sheet(isPresented: $showUpload) {
            WikiUploadView {
                await load()
            }
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Button {
                showUpload = true
            } label: {
                Label("Upload", systemImage: "square.and.arrow.up")
                    .font(.subheadline.weight(.medium))
            }
            .buttonStyle(.borderedProminent)
            .tint(ZTheme.primary)
            .disabled(app.permissions?.canUploadFiles == false)
            .accessibilityHint("Upload files or ingest a URL into the wiki")

            Spacer()

            Menu {
                Picker("Sort", selection: $sortRecent) {
                    Text("Name").tag(false)
                    Text("Recent").tag(true)
                }

                Divider()

                Button("Expand all") { expandAll() }
                Button("Collapse all") { expanded.removeAll() }
            } label: {
                Image(systemName: "arrow.up.arrow.down")
                    .foregroundStyle(ZTheme.mutedForeground)
            }
            .accessibilityLabel("Sort and expand wiki sections")
        }
        .padding(.horizontal)
        .padding(.bottom, 8)
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
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(ZTheme.background)
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
                    DisclosureGroup(isExpanded: expansionBinding(for: name)) {
                        ForEach(entries) { entry in
                            pageRow(entry, selectionMode: selectionMode)
                        }
                    } label: {
                        sectionHeader(
                            name.capitalized,
                            count: isFiltering ? entries.count : directory.files.count
                        )
                    }
                    .listRowBackground(ZTheme.background)
                }
            }
        }

        let roots = filtered(files.rootFiles)
        if !roots.isEmpty {
            DisclosureGroup(isExpanded: expansionBinding(for: "root")) {
                ForEach(roots) { entry in
                    pageRow(entry, selectionMode: selectionMode)
                }
            } label: {
                sectionHeader(
                    "Root",
                    count: isFiltering ? roots.count : files.rootFiles.count
                )
            }
            .listRowBackground(ZTheme.background)
        }
    }

    private func sectionHeader(_ title: String, count: Int) -> some View {
        HStack(spacing: 8) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(ZTheme.foreground)
            Text("\(count)")
                .font(.caption2)
                .foregroundStyle(ZTheme.mutedForeground)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(ZTheme.muted, in: Capsule())
        }
    }

    @ViewBuilder
    private func pageRow(_ entry: WikiFileEntry, selectionMode: Bool) -> some View {
        let ref = WikiPageRef(path: entry.relativePath)
        if selectionMode {
            WikiRow(entry: entry)
                .tag(ref)
                .listRowBackground(ZTheme.background)
        } else {
            NavigationLink(value: ref) {
                WikiRow(entry: entry)
            }
            .listRowBackground(ZTheme.background)
        }
    }

    private var isFiltering: Bool {
        !filter.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func expansionBinding(for key: String) -> Binding<Bool> {
        Binding(
            get: { isFiltering || expanded.contains(key) },
            set: { isOpen in
                if isOpen {
                    expanded.insert(key)
                } else {
                    expanded.remove(key)
                }
            }
        )
    }

    private func expandAll() {
        guard let files else { return }
        expanded = Set(files.directories.keys)
        expanded.insert("root")
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

    private func openPending(_ value: String?) {
        guard let value else { return }
        open(value, selectionMode: sizeClass == .regular)
        pendingPath = nil
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
                .foregroundStyle(ZTheme.foreground)

            if !entry.preview.isEmpty {
                Text(entry.preview)
                    .font(.caption)
                    .foregroundStyle(ZTheme.mutedForeground)
                    .lineLimit(2)
            }

            HStack(spacing: 6) {
                Text(entry.relativePath)
                    .lineLimit(1)
                Text("·")
                Text(entry.modifiedDate, format: .dateTime.year().month().day())
            }
            .font(.caption2)
            .foregroundStyle(ZTheme.mutedForeground.opacity(0.8))
        }
        .padding(.vertical, 2)
    }
}

extension String {
    var trimmed: String {
        trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
