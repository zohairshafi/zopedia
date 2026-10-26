import Foundation

public struct WikiFileEntry: Decodable, Hashable, Sendable, Identifiable {
    public let name: String
    public let relativePath: String
    public let size: Int
    public let modified: Double
    public let preview: String

    public var id: String { relativePath }
    public var modifiedDate: Date { Date(timeIntervalSince1970: modified) }

    enum CodingKeys: String, CodingKey {
        case name
        case relativePath = "relative_path"
        case size
        case modified
        case preview
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decodeIfPresent(String.self, forKey: .name) ?? ""
        relativePath = try container.decodeIfPresent(String.self, forKey: .relativePath) ?? ""
        size = try container.decodeIfPresent(Int.self, forKey: .size) ?? 0
        modified = try container.decodeIfPresent(Double.self, forKey: .modified) ?? 0
        preview = try container.decodeIfPresent(String.self, forKey: .preview) ?? ""
    }
}

public struct WikiDirectoryPayload: Decodable, Sendable {
    public let count: Int
    public let files: [WikiFileEntry]

    enum CodingKeys: String, CodingKey {
        case count
        case files
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        count = try container.decodeIfPresent(Int.self, forKey: .count) ?? 0
        files = try container.decodeIfPresent([WikiFileEntry].self, forKey: .files) ?? []
    }
}

public struct WikiFilesResponse: Decodable, Sendable {
    public let directories: [String: WikiDirectoryPayload]
    public let rootFiles: [WikiFileEntry]

    enum CodingKeys: String, CodingKey {
        case directories
        case rootFiles = "root_files"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        directories = try container.decodeIfPresent(
            [String: WikiDirectoryPayload].self, forKey: .directories
        ) ?? [:]
        rootFiles = try container.decodeIfPresent([WikiFileEntry].self, forKey: .rootFiles) ?? []
    }

    public var totalCount: Int {
        directories.values.reduce(0) { $0 + $1.count } + rootFiles.count
    }
}

public struct WikiQueryResponse: Decodable, Sendable {
    public let status: String
    public let answer: String
    public let answerPage: String?
    public let contextPages: [String]

    enum CodingKeys: String, CodingKey {
        case status
        case answer
        case answerPage = "answer_page"
        case contextPages = "context_pages"
    }
}

public struct WikiIngestResponse: Decodable, Sendable {
    public let status: String
    public let processedFiles: Int
    public let results: [JSONValue]

    enum CodingKeys: String, CodingKey {
        case status
        case processedFiles = "processed_files"
        case results
    }
}
