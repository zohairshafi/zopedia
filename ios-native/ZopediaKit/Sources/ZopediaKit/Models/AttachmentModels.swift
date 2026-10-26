import Foundation

public struct PDFExtractResponse: Decodable, Sendable {
    public let name: String
    public let text: String
    public let truncated: Bool
}

public struct UploadFailure: Decodable, Sendable {
    public let filename: String
    public let reason: String
}

public struct UploadResponse: Decodable, Sendable {
    public let status: String
    public let uploaded: [String]
    public let failed: [UploadFailure]
}
