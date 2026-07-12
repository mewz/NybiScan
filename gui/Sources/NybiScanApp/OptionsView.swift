import AppKit
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
                    // Reads the current flag and writes only on user toggle.
                    Toggle("Auto-start proxy on project open", isOn: Binding(
                        get: { model.config?.autoStartProxy ?? true },
                        set: { on in Task { await model.setAutoStartProxy(on) } }
                    ))
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

                Section("CA") {
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
                    HStack {
                        Button("Export PEM...") { exportCert(format: "pem") }
                        Button("Export DER...") { exportCert(format: "der") }
                        Button("Refresh CA info") { Task { await model.refreshCaInfo() } }
                    }
                    Text("""
                    Export and trust this CA to intercept HTTPS. Firefox uses its own \
                    trust store (Settings -> Privacy & Security -> Certificates -> \
                    Import), so trusting in the macOS keychain does not cover Firefox.
                    """)
                    .font(.caption).foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
        }
        .frame(width: 520, height: 560)
        .onAppear {
            if ip.isEmpty { ip = model.config?.defaultListenIp ?? "127.0.0.1" }
            if port.isEmpty { port = String(model.config?.defaultListenPort ?? 8080) }
        }
    }

    // The GUI owns the save dialog; the core owns the cert material (public cert
    // only, never the private key).
    private func exportCert(format: String) {
        Task {
            guard let (data, suggestedName) = await model.exportCACert(format: format) else { return }
            let panel = NSSavePanel()
            panel.nameFieldStringValue = suggestedName
            panel.canCreateDirectories = true
            if panel.runModal() == .OK, let url = panel.url {
                try? data.write(to: url)
            }
        }
    }
}
