import Foundation

public struct UploadFile: Sendable {
    public var name: String
    public var mimeType: String
    public var data: Data

    public init(name: String, mimeType: String, data: Data) {
        self.name = name
        self.mimeType = mimeType
        self.data = data
    }
}

public struct AttachmentService: Sendable {
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    /// Extract text from a PDF for use in the current conversation.
    public func extractPDF(data: Data, filename: String) async throws -> PDFExtractResponse {
        let body = try MultipartFormData.write(parts: [
            MultipartPart(
                fieldName: "file",
                filename: filename,
                mimeType: "application/pdf",
                data: data
            ),
        ])
        return try await client.upload("api/inference/extract-pdf", body: body)
    }

    /// Upload files into the wiki's raw folder. The server accepts multiple
    /// files under the same `files` field.
    public func uploadFiles(_ files: [UploadFile]) async throws -> UploadResponse {
        let parts = files.map {
            MultipartPart(
                fieldName: "files",
                filename: $0.name,
                mimeType: $0.mimeType,
                data: $0.data
            )
        }
        let body = try MultipartFormData.write(parts: parts)
        return try await client.upload("api/upload", body: body)
    }
}
