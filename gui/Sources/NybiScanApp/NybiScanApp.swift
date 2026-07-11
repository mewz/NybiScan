import AppKit
import SwiftUI

@main
struct NybiScanApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel.shared

    var body: some Scene {
        WindowGroup("NybiScan") {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 900, minHeight: 560)
                .task { await model.start() }
        }
        .windowStyle(.titleBar)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var signalSources: [DispatchSourceSignal] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        // A bare SwiftPM executable is not a bundled .app; make it a real
        // foreground windowed app.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)

        // Cmd-Q uses applicationWillTerminate; a SIGTERM/SIGINT (external kill,
        // Ctrl-C) must ALSO clean up the spawned core so it never orphans.
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            source.setEventHandler {
                MainActor.assumeIsolated { AppModel.shared.shutdownSync() }
                exit(0)
            }
            source.resume()
            signalSources.append(source)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        // Clean core shutdown (drain + WAL checkpoint), escalate if needed.
        MainActor.assumeIsolated {
            AppModel.shared.shutdownSync()
        }
    }
}
