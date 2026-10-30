import SwiftUI

/// The app's single colour source, matching the web client's light/dark tokens.
enum ZTheme {
    static let background = dynamic(light: 0xFFFFFF, dark: 0x1A1B1E)
    static let foreground = dynamic(light: 0x3F3F3F, dark: 0xD4D4D4)
    static let card = dynamic(light: 0xFFFFFF, dark: 0x222427)
    static let cardForeground = dynamic(light: 0x020906, dark: 0xD4D4D4)
    static let primary = dynamic(light: 0x14B789, dark: 0x14B789)
    static let primaryForeground = dynamic(light: 0xFFFFFF, dark: 0xFFFFFF)
    static let secondary = dynamic(light: 0xE1F8EE, dark: 0x2E3035)
    static let secondaryForeground = dynamic(light: 0x00341F, dark: 0xD4D4D4)
    static let muted = dynamic(light: 0xF7F7F7, dark: 0x2E3035)
    static let mutedForeground = dynamic(light: 0x717171, dark: 0x999999)
    static let destructive = dynamic(light: 0xEF4444, dark: 0xEF4444)
    static let border = dynamic(light: 0xDFE7E3, dark: 0x2E3035)
    static let input = dynamic(light: 0xDFE7E3, dark: 0x3A3D42)
    static let sidebar = dynamic(light: 0xFCFCFC, dark: 0x222427)
    static let userBubble = dynamic(light: 0xF5F5F5, dark: 0x222427)
    static let codeBlock = dynamic(light: 0xF6F6F6, dark: 0x181818)
    static let codeForeground = dynamic(light: 0x1F1F1F, dark: 0xE6E6E6)
    static let codeBlockBorder = Color(uiColor: UIColor { trait in
        trait.userInterfaceStyle == .dark
            ? UIColor.white.withAlphaComponent(0.07)
            : UIColor.black.withAlphaComponent(0.08)
    })

    static let cardRadius: CGFloat = 16
    static let rowRadius: CGFloat = 10
    static let bubbleRadius: CGFloat = 16

    static var cardShape: RoundedRectangle {
        RoundedRectangle(cornerRadius: cardRadius, style: .continuous)
    }

    static var rowShape: RoundedRectangle {
        RoundedRectangle(cornerRadius: rowRadius, style: .continuous)
    }

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(uiColor: UIColor { trait in
            UIColor(hex: trait.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

private extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}
