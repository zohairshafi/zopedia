import ObjectiveC
import SwiftUI
import UIKit

extension Notification.Name {
    static let chatScrollToBottom = Notification.Name("zopedia.chat.scrollToBottom")
}

/// SwiftUI's TabView does not expose re-taps on the selected tab. Observe the
/// underlying UITabBarController delegate and post a notification when Chat is
/// selected, so the chat can scroll to the latest message. The post is delayed
/// until after the system's own scroll-to-top gesture has run.
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
        if let controller = Self.findTabBarController(window.rootViewController) {
            if !(controller.delegate is ChatTabBarDelegate) {
                let proxy = ChatTabBarDelegate(previous: controller.delegate)
                objc_setAssociatedObject(
                    controller,
                    &chatDelegateKey,
                    proxy,
                    .OBJC_ASSOCIATION_RETAIN_NONATOMIC
                )
                controller.delegate = proxy
            }
            return
        }

        if attempt < 10 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                self?.install(attempt: attempt + 1)
            }
        }
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

nonisolated(unsafe) private var chatDelegateKey: UInt8 = 0

private final class ChatTabBarDelegate: NSObject, UITabBarControllerDelegate {
    private weak var previous: UITabBarControllerDelegate?

    init(previous: UITabBarControllerDelegate?) {
        self.previous = previous
    }

    func tabBarController(
        _ tabBarController: UITabBarController,
        didSelect viewController: UIViewController
    ) {
        if viewController.tabBarItem.title == "Chat" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                NotificationCenter.default.post(name: .chatScrollToBottom, object: nil)
            }
        }
        previous?.tabBarController?(tabBarController, didSelect: viewController)
    }

    override func responds(to selector: Selector!) -> Bool {
        super.responds(to: selector) || previous?.responds(to: selector) == true
    }

    override func forwardingTarget(for selector: Selector!) -> Any? {
        if previous?.responds(to: selector) == true {
            return previous
        }
        return super.forwardingTarget(for: selector)
    }
}
