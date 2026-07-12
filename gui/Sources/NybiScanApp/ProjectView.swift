import AppKit
import SwiftUI

struct ProjectView: View {
    @EnvironmentObject var model: AppModel
    @State private var newName = "MyProject"
    @State private var encrypt = false
    @State private var newPassphrase = ""
    @State private var openPassphrase = ""

    var body: some View {
        VStack(spacing: 20) {
            Text("NybiScan").font(.largeTitle.bold())
            Text("Open or create a project to begin.").foregroundStyle(.secondary)

            GroupBox("New project") {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Name", text: $newName)
                    Toggle("Encrypt at rest (passphrase)", isOn: $encrypt)
                    if encrypt {
                        SecureField("Passphrase", text: $newPassphrase)
                    }
                    Button("Choose location and create...") { createFlow() }
                }
                .padding(8)
            }

            GroupBox("Open existing project") {
                VStack(alignment: .leading, spacing: 8) {
                    SecureField("Passphrase (only if encrypted)", text: $openPassphrase)
                    Button("Choose a .nybiscan bundle...") { openFlow() }
                }
                .padding(8)
            }

            if let e = model.lastError {
                Text(e).foregroundStyle(.red).font(.caption).frame(maxWidth: 460)
            }
        }
        .padding(40)
        .frame(maxWidth: 540)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func createFlow() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "\(newName).nybiscan"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let passphrase = encrypt ? newPassphrase : nil
        Task { await model.createProject(path: url.path, name: newName, passphrase: passphrase) }
    }

    private func openFlow() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let passphrase = openPassphrase.isEmpty ? nil : openPassphrase
        Task { await model.openProject(path: url.path, passphrase: passphrase) }
    }
}
