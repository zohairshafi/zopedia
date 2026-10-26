import SwiftUI

struct RootView: View {
    @Environment(AppEnvironment.self) private var app

    var body: some View {
        Group {
            switch app.phase {
            case .launching:
                ProgressView("Connecting…")
            case .connect:
                ConnectView()
            case .changePassword:
                ChangePasswordView()
            case .ready:
                MainView()
            }
        }
        .animation(.default, value: app.phase)
    }
}
