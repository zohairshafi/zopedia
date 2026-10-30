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
        view.paintKeyboardWindows()
    }
}

private final class BackgroundView: UIView {
    var color: UIColor = .clear {
        didSet {
            window?.backgroundColor = color
            paintKeyboardWindows()
        }
    }

    private var observingKeyboard = false

    override func didMoveToWindow() {
        super.didMoveToWindow()
        window?.backgroundColor = color

        guard !observingKeyboard else { return }
        observingKeyboard = true
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(keyboardWillShow),
            name: UIResponder.keyboardWillShowNotification,
            object: nil
        )
    }

    @objc private func keyboardWillShow() {
        paintKeyboardWindows()
        // The text-effects window may be created just after the notification.
        for delay in [0.15, 0.5] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.paintKeyboardWindows()
            }
        }
    }

    /// iOS 26's keyboard is a rounded panel; the system's text-effects window
    /// behind it is black by default, which shows at the panel's corners.
    func paintKeyboardWindows() {
        guard color != .clear else { return }
        for scene in UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }) {
            for candidate in scene.windows
            where String(describing: type(of: candidate)) == "UITextEffectsWindow" {
                candidate.backgroundColor = color
            }
        }
    }
}
