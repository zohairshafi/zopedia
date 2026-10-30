import SwiftUI

/// The web app's main logo, with light and dark asset variants.
struct ZopediaLogo: View {
    var size: CGFloat = 96

    var body: some View {
        Image("Logo")
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}
