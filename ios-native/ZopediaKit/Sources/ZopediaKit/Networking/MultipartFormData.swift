import Foundation

public struct MultipartPart: Sendable {
    public var fieldName: String
    public var filename: String
    public var mimeType: String
    public var data: Data

    public init(fieldName: String, filename: String, mimeType: String, data: Data) {
        self.fieldName = fieldName
        self.filename = filename
        self.mimeType = mimeType
        self.data = data
    }
}

public struct MultipartBody: Sendable {
    public let fileURL: URL
    public let boundary: String

    public var contentType: String {
        "multipart/form-data; boundary=\(boundary)"
    }
}

public enum MultipartFormData {
    /// Write the body to a temp file so large uploads are not held in memory.
    public static func write(
        parts: [MultipartPart],
        boundary: String = "Boundary-\(UUID().uuidString)"
    ) throws -> MultipartBody {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("zopedia-upload-\(UUID().uuidString)")
        try Data().write(to: url)
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }

        for part in parts {
            try handle.write(contentsOf: Data("--\(boundary)\r\n".utf8))
            let disposition = "Content-Disposition: form-data; "
                + "name=\"\(escape(part.fieldName))\"; "
                + "filename=\"\(escape(part.filename))\"\r\n"
            try handle.write(contentsOf: Data(disposition.utf8))
            try handle.write(contentsOf: Data("Content-Type: \(part.mimeType)\r\n\r\n".utf8))
            try handle.write(contentsOf: part.data)
            try handle.write(contentsOf: Data("\r\n".utf8))
        }

        try handle.write(contentsOf: Data("--\(boundary)--\r\n".utf8))
        return MultipartBody(fileURL: url, boundary: boundary)
    }

    /// Strip any path components and escape characters that would break the header.
    public static func escape(_ value: String) -> String {
        var cleaned = value
        if let slash = cleaned.lastIndex(of: "/") {
            cleaned = String(cleaned[cleaned.index(after: slash)...])
        }
        if let slash = cleaned.lastIndex(of: "\\") {
            cleaned = String(cleaned[cleaned.index(after: slash)...])
        }
        cleaned = cleaned
            .replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
        return cleaned
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
