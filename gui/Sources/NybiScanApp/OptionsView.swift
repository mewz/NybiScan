import SwiftUI

struct OptionsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var ip = ""
    @State private var port = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Options").font(.title2.bold())
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding()
            Divider()

            Form {
                Section("Proxy") {
                    TextField("Listen IP", text: $ip)
                    TextField("Listen port", text: $port)
                    HStack {
                        Button("Start") {
                            let p = Int(port) ?? 8080
                            Task { await model.proxyStart(ip: ip, port: p) }
                        }
                        Button("Stop") { Task { await model.proxyStop() } }
                        Button("Refresh") { Task { await model.refreshProxyStatus() } }
                    }
                    if let s = model.proxyStatus {
                        LabeledContent("Running", value: s.running ? "yes" : "no")
                        LabeledContent("ssl_insecure", value: (s.sslInsecure ?? false) ? "true" : "false")
                        if let host = s.listenHost, let lport = s.listenPort {
                            LabeledContent("Listening on", value: "\(host):\(lport)")
                        }
                    }
                }

                Section("CA (read-only)") {
                    if let ca = model.caInfo {
                        LabeledContent("Scope", value: ca.scope)
                        if ca.exists {
                            LabeledContent("Common name", value: ca.cn ?? "-")
                            LabeledContent("SHA-256", value: ca.fingerprintSha256 ?? "-")
                        } else {
                            Text("No CA resolves yet. Generate one with `nybiscan ca generate`.")
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        Text("Loading...").foregroundStyle(.secondary)
                    }
                    Button("Refresh CA info") { Task { await model.refreshCaInfo() } }
                }
            }
            .formStyle(.grouped)
        }
        .frame(width: 480, height: 460)
        .onAppear {
            if ip.isEmpty { ip = model.config?.defaultListenIp ?? "127.0.0.1" }
            if port.isEmpty { port = String(model.config?.defaultListenPort ?? 8080) }
        }
    }
}
