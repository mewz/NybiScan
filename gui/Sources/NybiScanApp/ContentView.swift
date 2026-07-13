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
                SectionContainer()
            } else {
                ProjectView()
            }
        }
    }
}

/// Holds all three section views ALIVE (opacity-toggled) so switching tabs never
/// rebuilds them - scroll position, selection, and sort survive the switch (the
/// reset-on-reappear family). Owns the single section Picker and the spider start
/// sheet, so those work regardless of the active section.
struct SectionContainer: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ZStack {
            MainView().opacity(model.section == .history ? 1 : 0)
                .allowsHitTesting(model.section == .history)
            BenchView().opacity(model.section == .bench ? 1 : 0)
                .allowsHitTesting(model.section == .bench)
            DashboardView().opacity(model.section == .dashboard ? 1 : 0)
                .allowsHitTesting(model.section == .dashboard)
        }
        .toolbar {
            ToolbarItem(placement: .principal) {
                Picker("", selection: $model.section) {
                    Text("History").tag(AppSection.history)
                    Text("Bench").tag(AppSection.bench)
                    Text("Dashboard").tag(AppSection.dashboard)
                }
                .pickerStyle(.segmented).frame(width: 280)
            }
        }
        .sheet(isPresented: Binding(
            get: { model.spiderDraft != nil }, set: { if !$0 { model.spiderDraft = nil } })
        ) { SpiderStartSheet() }
        .alert("Spider", isPresented: Binding(
            get: { model.spiderError != nil }, set: { if !$0 { model.spiderError = nil } })
        ) {
            Button("OK", role: .cancel) { model.spiderError = nil }
        } message: { Text(model.spiderError ?? "") }
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
