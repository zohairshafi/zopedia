import SwiftUI
import UIKit

extension Notification.Name {
    static let chatScrollToBottom = Notification.Name("zopedia.chat.scrollToBottom")
    static let selectChatTab = Notification.Name("zopedia.chat.selectTab")
}

/// SwiftUI's TabView does not expose re-taps on the selected tab. Put a
/// transparent control above the native Chat item: a Chat tap selects the tab
/// and scrolls to the latest message without ever reaching the system's
/// scroll-to-top. The other tabs and the status-bar gesture keep their native
/// behavior.
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
    private weak var overlayContainer: UIView?
    private var boundsObservation: NSKeyValueObservation?
    private var selectionObservation: NSKeyValueObservation?

    override func didMoveToWindow() {
        super.didMoveToWindow()
        guard window != nil else {
            removeOverlay()
            return
        }
        install(attempt: 0)
    }

    func install(attempt: Int) {
        guard let window else { return }
        if let controller = Self.findTabBarController(window.rootViewController),
           controller.tabBar.superview != nil {
            installOverlay(on: controller.tabBar, controller: controller)
            return
        }

        if attempt < 10 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                self?.install(attempt: attempt + 1)
            }
        }
    }

    private func installOverlay(
        on tabBar: UITabBar,
        controller: UITabBarController
    ) {
        guard let container = tabBar.superview else { return }

        if let existing = container.viewWithTag(ChatTabOverlay.tag) as? ChatTabOverlay {
            existing.frame = Self.chatFrame(in: tabBar, in: container)
            container.bringSubviewToFront(existing)
            return
        }

        removeOverlay()

        let overlay = ChatTabOverlay()
        overlay.action = {
            NotificationCenter.default.post(name: .selectChatTab, object: nil)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                NotificationCenter.default.post(name: .chatScrollToBottom, object: nil)
            }
        }
        container.addSubview(overlay)
        overlay.frame = Self.chatFrame(in: tabBar, in: container)
        container.bringSubviewToFront(overlay)
        overlayContainer = container

        // The tab bar brings its selected item forward after layout. Keep the
        // intercepting control above the whole bar so a re-tap never reaches
        // that item.
        boundsObservation = tabBar.observe(\.bounds, options: [.new]) { [weak self, weak tabBar, weak container] _, _ in
            guard let self, let tabBar, let container else { return }
            DispatchQueue.main.async {
                self.repositionOverlay(on: tabBar, in: container)
            }
        }
        selectionObservation = controller.observe(\.selectedIndex, options: [.new]) { [weak self, weak tabBar, weak container] _, _ in
            guard let self, let tabBar, let container else { return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                self.repositionOverlay(on: tabBar, in: container)
            }
        }

        for delay in [0.1, 0.5, 1.0] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self, weak tabBar, weak container] in
                guard let self, let tabBar, let container else { return }
                self.repositionOverlay(on: tabBar, in: container)
            }
        }
    }

    private func removeOverlay() {
        overlayContainer?.viewWithTag(ChatTabOverlay.tag)?.removeFromSuperview()
        overlayContainer = nil
        boundsObservation = nil
        selectionObservation = nil
    }

    private func repositionOverlay(on tabBar: UITabBar, in container: UIView) {
        guard let overlay = container.viewWithTag(ChatTabOverlay.tag) as? ChatTabOverlay else {
            return
        }
        overlay.frame = Self.chatFrame(in: tabBar, in: container)
        container.bringSubviewToFront(overlay)
    }

    private static func chatFrame(in tabBar: UITabBar, in container: UIView) -> CGRect {
        guard let items = tabBar.items,
              let chatIndex = items.firstIndex(where: { $0.title == "Chat" }) else {
            return .zero
        }

        let controls = controls(in: tabBar)
            .map { (control: $0, frame: $0.convert($0.bounds, to: container)) }
            .sorted { $0.frame.minX < $1.frame.minX }

        if controls.indices.contains(chatIndex),
           controls[chatIndex].frame.width > 0,
           controls[chatIndex].frame.height > 0 {
            return controls[chatIndex].frame
        }

        let barFrame = tabBar.convert(tabBar.bounds, to: container)
        let width = barFrame.width / CGFloat(max(items.count, 1))
        return CGRect(x: barFrame.minX, y: barFrame.minY, width: width, height: barFrame.height)
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
}

private final class ChatTabOverlay: UIControl {
    static let tag = 0x5A0B

    var action: (() -> Void)?

    init() {
        super.init(frame: .zero)
        backgroundColor = .clear
        isAccessibilityElement = false
        addTarget(self, action: #selector(tapped), for: .touchUpInside)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    @objc private func tapped() {
        action?()
    }
}
