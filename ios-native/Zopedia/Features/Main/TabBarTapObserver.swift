import SwiftUI
import UIKit

extension Notification.Name {
    static let chatScrollToBottom = Notification.Name("zopedia.chat.scrollToBottom")
}

/// SwiftUI's TabView does not expose re-taps on the selected tab. Observe the
/// underlying UITabBar and post a notification when Chat is tapped, so the
/// chat can scroll to the latest message instead of the system's scroll-to-top.
struct TabBarTapObserver: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView {
        let view = ObserverView()
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        (uiView as? ObserverView)?.install(attempt: 0)
    }
}

private final class ObserverView: UIView {
    override func didMoveToWindow() {
        super.didMoveToWindow()
        guard window != nil else { return }
        install(attempt: 0)
    }

    func install(attempt: Int) {
        guard let window else { return }
        if let tabBar = Self.findTabBar(in: window) {
            let name = "zopedia.chatTabTap"
            if tabBar.gestureRecognizers?.contains(where: { $0.name == name }) != true {
                let gesture = UITapGestureRecognizer(
                    target: ChatTabTapRelay.shared,
                    action: #selector(ChatTabTapRelay.tapped(_:))
                )
                gesture.name = name
                gesture.cancelsTouchesInView = false
                tabBar.addGestureRecognizer(gesture)
            }
            return
        }

        if attempt < 10 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                self?.install(attempt: attempt + 1)
            }
        }
    }

    private static func findTabBar(in window: UIWindow) -> UITabBar? {
        if let controller = findTabBarController(window.rootViewController) {
            return controller.tabBar
        }
        return findTabBarView(window)
    }

    private static func findTabBarController(
        _ controller: UIViewController?
    ) -> UITabBarController? {
        guard let controller else { return nil }
        if let tab = controller as? UITabBarController { return tab }
        for child in controller.children {
            if let tab = findTabBarController(child) { return tab }
        }
        return findTabBarController(controller.presentedViewController)
    }

    private static func findTabBarView(_ view: UIView) -> UITabBar? {
        if let tab = view as? UITabBar { return tab }
        for child in view.subviews {
            if let tab = findTabBarView(child) { return tab }
        }
        return nil
    }
}

private final class ChatTabTapRelay: NSObject, @unchecked Sendable {
    static let shared = ChatTabTapRelay()

    @objc func tapped(_ gesture: UITapGestureRecognizer) {
        guard let tabBar = gesture.view as? UITabBar,
              let items = tabBar.items,
              let chatIndex = items.firstIndex(where: { $0.title == "Chat" }) else {
            return
        }

        let point = gesture.location(in: tabBar)
        let controls = Self.controls(in: tabBar)
            .map { (control: $0, frame: $0.convert($0.bounds, to: tabBar)) }
            .sorted { $0.frame.minX < $1.frame.minX }

        if controls.indices.contains(chatIndex), controls[chatIndex].frame.contains(point) {
            post()
            return
        }

        var hit = tabBar.hitTest(point, with: nil)
        while let view = hit, view !== tabBar {
            if let label = view.accessibilityLabel, label.hasPrefix("Chat") {
                post()
                return
            }
            hit = view.superview
        }
    }

    private func post() {
        NotificationCenter.default.post(name: .chatScrollToBottom, object: nil)
    }

    private static func controls(in view: UIView) -> [UIControl] {
        var result: [UIControl] = []
        for child in view.subviews {
            if let control = child as? UIControl {
                result.append(control)
            }
            result.append(contentsOf: controls(in: child))
        }
        return result
    }
}

/// Keeps the system's tab re-tap from scrolling the chat to the top.
struct ScrollToTopDisabler: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView {
        let view = DisablerView()
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {}
}

private final class DisablerView: UIView {
    override func didMoveToWindow() {
        super.didMoveToWindow()
        disable()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        if window != nil { disable() }
    }

    private func disable() {
        var view: UIView? = superview
        while let candidate = view {
            if let scroll = candidate as? UIScrollView {
                scroll.scrollsToTop = false
                return
            }
            view = candidate.superview
        }
    }
}
