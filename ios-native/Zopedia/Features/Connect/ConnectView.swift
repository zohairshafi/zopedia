import SwiftUI
import ZopediaKit

struct ConnectView: View {
    @Environment(AppEnvironment.self) private var app

    @State private var url = ""
    @State private var username = ""
    @State private var password = ""
    @State private var showPassword = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 10) {
                        ZopediaLogo(size: 96)
                        Text("Zopedia")
                            .font(.title2.weight(.semibold))
                        Text("Sign in to your self-hosted knowledge base.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                }
                .listRowBackground(Color.clear)

                Section("Server") {
                    TextField("http://192.168.2.23:8080", text: $url)
                        .textContentType(.URL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    ForEach(app.serverStore.recentServers) { server in
                        Button {
                            url = server.url
                            username = server.username
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(server.url)
                                    .font(.callout)
                                Text(server.username)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                Section("Account") {
                    TextField("Username", text: $username)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    HStack {
                        Group {
                            if showPassword {
                                TextField("Password", text: $password)
                            } else {
                                SecureField("Password", text: $password)
                            }
                        }
                        .textContentType(.password)

                        Button {
                            showPassword.toggle()
                        } label: {
                            Image(systemName: showPassword ? "eye.slash" : "eye")
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(showPassword ? "Hide password" : "Show password")
                    }
                }

                if let error = app.errorMessage {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.callout)
                    }
                }

                Section {
                    Button {
                        Task {
                            await app.connect(
                                urlText: url,
                                username: username,
                                password: password
                            )
                        }
                    } label: {
                        HStack {
                            Spacer()
                            if app.isBusy {
                                ProgressView()
                            } else {
                                Text("Connect")
                            }
                            Spacer()
                        }
                    }
                    .disabled(app.isBusy || url.trimmingCharacters(in: .whitespaces).isEmpty)
                } footer: {
                    Text("Plain http:// works for local addresses only. Public servers must use https://.")
                }
            }
            .navigationTitle("Connect")
            .onAppear {
                if url.isEmpty {
                    url = app.serverStore.serverURL ?? ""
                }
            }
        }
    }
}
