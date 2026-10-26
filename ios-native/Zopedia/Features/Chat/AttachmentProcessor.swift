import Foundation
import ImageIO
import UIKit

struct PreparedImage: Sendable {
    let base64: String
    let fileName: String
    let jpegData: Data
}

enum AttachmentProcessingError: LocalizedError {
    case tooLarge
    case unreadable

    var errorDescription: String? {
        switch self {
        case .tooLarge:
            return "That image is larger than 20 MB."
        case .unreadable:
            return "That image could not be read."
        }
    }
}

enum AttachmentProcessor {
    static let maxBytes = 20 * 1024 * 1024
    static let maxDimension = 2048

    /// Downscale, orient, flatten onto white, and JPEG-encode for the model.
    static func prepareImage(from data: Data) throws -> PreparedImage {
        guard data.count <= maxBytes else { throw AttachmentProcessingError.tooLarge }
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else {
            throw AttachmentProcessingError.unreadable
        }

        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxDimension,
        ]
        guard let cgImage = CGImageSourceCreateThumbnailAtIndex(
            source, 0, options as CFDictionary
        ) else {
            throw AttachmentProcessingError.unreadable
        }

        let size = CGSize(width: cgImage.width, height: cgImage.height)
        let format = UIGraphicsImageRendererFormat()
        format.opaque = true
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: size, format: format)
        let image = renderer.image { context in
            UIColor.white.setFill()
            context.fill(CGRect(origin: .zero, size: size))
            UIImage(cgImage: cgImage).draw(in: CGRect(origin: .zero, size: size))
        }

        guard var jpeg = image.jpegData(compressionQuality: 0.82) else {
            throw AttachmentProcessingError.unreadable
        }
        if jpeg.count > 4 * 1024 * 1024 {
            jpeg = image.jpegData(compressionQuality: 0.6) ?? jpeg
        }
        guard jpeg.count <= maxBytes else { throw AttachmentProcessingError.tooLarge }

        return PreparedImage(
            base64: jpeg.base64EncodedString(),
            fileName: UUID().uuidString + ".jpg",
            jpegData: jpeg
        )
    }

    static func save(_ data: Data, named name: String, in directory: URL) throws {
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        try data.write(to: directory.appendingPathComponent(name), options: .atomic)
    }
}
