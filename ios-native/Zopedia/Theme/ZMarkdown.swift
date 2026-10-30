import MarkdownUI
import os
import SwiftMath
import SwiftUI
import UIKit
import ZopediaKit

/// Markdown with web-parity wiki links and LaTeX math.
///
/// `LaTeXPreprocessor` turns math spans into `zopedia-math` images;
/// `MathImageRenderer` rasterises them with SwiftMath. The image's baseline is
/// baked in so inline math lines up with the surrounding text.
struct ZMarkdown: View {
    @Environment(\.colorScheme) private var colorScheme

    let text: String

    var body: some View {
        let dark = colorScheme == .dark
        let bodySize = UIFontMetrics(forTextStyle: .body).scaledValue(for: 17)

        Markdown(WikiLinkPreprocessor.preprocess(LaTeXPreprocessor.preprocess(text)))
            .markdownTheme(.zopedia)
            .markdownInlineImageProvider(
                MathInlineImageProvider(dark: dark, fontSize: bodySize)
            )
            .markdownImageProvider(
                MathBlockImageProvider(dark: dark, fontSize: bodySize * 1.08)
            )
    }
}

private struct MathImageKey: Hashable {
    let latex: String
    let display: Bool
    let dark: Bool
    let fontSize: CGFloat
}

@MainActor
final class MathImageRenderer {
    static let shared = MathImageRenderer()

    private static let logger = Logger(subsystem: "com.zopedia.client", category: "math")

    private var cache: [MathImageKey: UIImage] = [:]
    private var order: [MathImageKey] = []

    func image(for request: MathImageRequest, dark: Bool, fontSize: CGFloat) -> UIImage {
        let size = (fontSize * 2).rounded() / 2
        let key = MathImageKey(
            latex: request.latex,
            display: request.display,
            dark: dark,
            fontSize: size
        )
        if let cached = cache[key] {
            return cached
        }

        let color = UIColor(ZTheme.foreground).resolvedColor(
            with: UITraitCollection(userInterfaceStyle: dark ? .dark : .light)
        )
        var math = MathImage(
            latex: request.latex,
            fontSize: size,
            textColor: color,
            labelMode: request.display ? .display : .text,
            textAlignment: .left
        )
        let (error, rendered, layout) = math.asImage()

        let image: UIImage
        if error == nil, let rendered {
            // Custom images in SwiftUI Text are anchored by their bottom edge.
            // Declaring the real baseline keeps descenders (fractions, sums)
            // below the text baseline instead of floating the equation.
            image = rendered.withBaselineOffset(fromBottom: layout?.descent ?? 0)
        } else {
            Self.logger.error(
                "Could not render LaTeX: \(error?.localizedDescription ?? "unknown", privacy: .public)"
            )
            image = fallbackImage(for: request.latex, color: color, fontSize: size)
        }

        cache[key] = image
        order.append(key)
        if order.count > 120 {
            let evicted = order.removeFirst()
            cache[evicted] = nil
        }
        return image
    }

    private func fallbackImage(for latex: String, color: UIColor, fontSize: CGFloat) -> UIImage {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.monospacedSystemFont(ofSize: fontSize * 0.9, weight: .regular),
            .foregroundColor: color,
        ]
        let text = latex as NSString
        let size = text.size(withAttributes: attributes)
        let bounds = CGRect(
            x: 0,
            y: 0,
            width: size.width + 4,
            height: size.height + 2
        )
        let renderer = UIGraphicsImageRenderer(size: bounds.size)
        return renderer.image { _ in
            text.draw(at: CGPoint(x: 2, y: 1), withAttributes: attributes)
        }
    }
}

enum MathImageRequest {
    case inline(String)
    case display(String)

    init?(url: URL) {
        guard url.scheme == "zopedia-math",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let latex = components.queryItems?.first(where: { $0.name == "tex" })?.value,
              !latex.isEmpty else {
            return nil
        }
        switch url.host {
        case "display": self = .display(latex)
        case "inline": self = .inline(latex)
        default: return nil
        }
    }

    var latex: String {
        switch self {
        case .inline(let latex), .display(let latex): return latex
        }
    }

    var display: Bool {
        switch self {
        case .display: return true
        case .inline: return false
        }
    }
}

private struct MathInlineImageProvider: InlineImageProvider {
    let dark: Bool
    let fontSize: CGFloat

    func image(with url: URL, label: String) async throws -> Image {
        guard let request = MathImageRequest(url: url) else {
            return Image(systemName: "exclamationmark.triangle")
        }
        return await MainActor.run {
            Image(uiImage: MathImageRenderer.shared.image(
                for: request,
                dark: dark,
                fontSize: fontSize
            ))
        }
    }
}

private struct MathBlockImageProvider: ImageProvider {
    let dark: Bool
    let fontSize: CGFloat

    func makeImage(url: URL?) -> some View {
        MathBlockImage(url: url, dark: dark, fontSize: fontSize)
    }
}

private struct MathBlockImage: View {
    let url: URL?
    let dark: Bool
    let fontSize: CGFloat

    var body: some View {
        if let url, let request = MathImageRequest(url: url) {
            let image = MathImageRenderer.shared.image(
                for: request,
                dark: dark,
                fontSize: fontSize
            )
            ViewThatFits(in: .horizontal) {
                Image(uiImage: image)
                ScrollView(.horizontal, showsIndicators: false) {
                    Image(uiImage: image)
                }
            }
            .frame(maxWidth: .infinity, alignment: .center)
        } else {
            EmptyView()
        }
    }
}
