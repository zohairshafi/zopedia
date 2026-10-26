import SwiftUI

struct ChangePasswordView: View {
    @Environment(AppEnvironment.self) private var app

    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var confirmation = ""

    private var forced: Bool {
        app.serverStore.mustChangePassword
    }

    private var localError: String? {
        if newPassword.count < 8 {
            return "The new password must be at least 8 characters."
        }
        if newPassword != confirmation {
            return "The passwords do not match."
        }
        return nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(forced
                         ? "Your account requires a new password before you can continue."
                         : "Update the password for this server.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }

                if !forced {
                    Section("Current password") {
                        SecureField("Current password", text: $currentPassword)
                            .textContentType(.password)
                    }
                }

                Section("New password") {
                    SecureField("At least 8 characters", text: $newPassword)
                        .textContentType(.newPassword)
                    SecureField("Confirm new password", text: $confirmation)
                        .textContentType(.newPassword)
                }

                if let message = app.errorMessage ?? localError {
                    Section {
                        Text(message)
                            .foregroundStyle(.red)
                            .font(.callout)
                    }
                }

                Section {
                    Button {
                        Task {
                            await app.changePassword(
                                current: forced ? "" : currentPassword,
                                new: newPassword
                            )
                        }
                    } label: {
                        HStack {
                            Spacer()
                            if app.isBusy {
                                ProgressView()
                            } else {
                                Text("Update password")
                            }
                            Spacer()
                        }
                    }
                    .disabled(app.isBusy || localError != nil)

                    Button("Disconnect", role: .destructive) {
                        Task { await app.disconnect() }
                    }
                }
            }
            .navigationTitle("Change password")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
