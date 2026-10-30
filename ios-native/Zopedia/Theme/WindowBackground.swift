import SwiftUI
import UIKit

/// Paint the window with the app background. The window stays black by
/// default, which shows through translucent keyboards and around sheets.
struct WindowBackground: UIViewRepresentable {
    @Environment(\.colorScheme) private var colorScheme

    func makeUIView(context: Context) -> UIView {
        let view = BackgroundView()
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        guard let view = uiView as? BackgroundView else { return }
        let style: UIUserInterfaceStyle = colorScheme == .dark ? .dark : .light
        let color = UIColor(ZTheme.background).resolvedColor(
            with: UITraitCollection(userInterfaceStyle: style)
        )
        view.color = color
        view.window?.backgroundColor = color
    }
}

private final class BackgroundView: UIView {
    var color: UIColor = .clear {
        didSet { window?.backgroundColor = color }
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        window?.backgroundColor = color
    }
}
