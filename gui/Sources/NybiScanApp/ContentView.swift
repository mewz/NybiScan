import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        switch model.phase {
        case .starting:
            StartingView()
        case .error(let message):
            ErrorView(message: message)
        case .needsAck:
            AuthGateView()
        case .ready:
            if model.project?.projectOpen == true {
                switch model.section {
                case .history: MainView()
                case .bench: BenchView()
                }
            } else {
                ProjectView()
            }
        }
    }
}

struct StartingView: View {
    var body: some View {
        VStack(spacing: 12) {
            ProgressView()
            Text("Starting the NybiScan core...").foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ErrorView: View {
    let message: String
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36)).foregroundStyle(.orange)
            Text("The core could not start").font(.title2.bold())
            Text(message)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .frame(maxWidth: 520)
            Button("Retry") { Task { await model.start() } }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct AuthGateView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "shield.lefthalf.filled").font(.system(size: 40))
            Text("Authorized use only").font(.title.bold())
            Text("""
            NybiScan is for authorized security testing only. Use it only against \
            systems you own or have explicit written permission to test.
            """)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 460)
            .foregroundStyle(.secondary)
            Button("I acknowledge") { Task { await model.acknowledge() } }
                .keyboardShortcut(.defaultAction)
            if let e = model.lastError {
                Text(e).foregroundStyle(.red).font(.caption)
            }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
