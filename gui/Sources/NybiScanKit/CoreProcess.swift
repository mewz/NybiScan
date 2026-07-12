import Foundation
#if canImport(Darwin)
import Darwin
#endif

public enum CoreProcessError: Error, Equatable {
    case binaryNotFound(String)
}

/// Spawns and supervises the Python core (the control API via `nybiscan serve`).
/// This is the GUI's ONE shell-out. Everything else goes through the control API.
public final class CoreProcess {
    private let process = Process()
    public let binPath: String
    public let arguments: [String]

    public init(binPath: String = CoreProcess.defaultBinPath(), arguments: [String] = ["serve"]) {
        self.binPath = binPath
        self.arguments = arguments
    }

    /// Resolve the core binary. Overridable via NYBISCAN_BIN. Otherwise walk up
    /// from the running executable to find the repo venv (.venv/bin/nybiscan),
    /// which works for both a directly-run binary and an `open`ed .app sitting in
    /// the repo (open does not pass shell env). A distributed .app moved out of
    /// the repo must set NYBISCAN_BIN (see DECISIONS.md).
    public static func defaultBinPath() -> String {
        let fm = FileManager.default
        if let override = ProcessInfo.processInfo.environment["NYBISCAN_BIN"], !override.isEmpty {
            return override
        }
        if let exec = Bundle.main.executableURL?.resolvingSymlinksInPath() {
            var dir = exec.deletingLastPathComponent()
            for _ in 0..<8 {
                let candidate = dir.appendingPathComponent(".venv/bin/nybiscan")
                if fm.isExecutableFile(atPath: candidate.path) { return candidate.path }
                dir = dir.deletingLastPathComponent()
            }
        }
        return fm.currentDirectoryPath + "/.venv/bin/nybiscan"
    }

    public var isRunning: Bool { process.isRunning }
    public var pid: Int32 { process.processIdentifier }

    /// Actionable message when the core binary cannot be located, naming the exact
    /// expected `.venv` and the exact fix. Used instead of the opaque
    /// health-timeout symptom so a missing/misnamed repo `.venv` is obvious.
    public static func notFoundMessage(binPath: String) -> String {
        // binPath is <root>/.venv/bin/nybiscan; the venv is two levels up.
        let bin = binPath as NSString
        let venv = (bin.deletingLastPathComponent as NSString).deletingLastPathComponent
        return """
        NybiScan core not found. Expected a Python environment at \(venv).

        From the repo root, run:
          python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
        (a `make setup` shortcut is coming in a later plan), then relaunch NybiScan.app.
        """
    }

    public func start() throws {
        guard FileManager.default.isExecutableFile(atPath: binPath) else {
            throw CoreProcessError.binaryNotFound(binPath)
        }
        process.executableURL = URL(fileURLWithPath: binPath)
        process.arguments = arguments
        try process.run()
    }

    /// SIGTERM first so the core drains the writer and checkpoints the WAL; wait
    /// a bounded time; escalate to SIGKILL if it will not exit. Never hang on quit,
    /// never leave a zombie.
    public func terminate(graceSeconds: Double = 5) {
        guard process.isRunning else { return }
        process.terminate()  // SIGTERM
        let deadline = Date().addingTimeInterval(graceSeconds)
        while process.isRunning && Date() < deadline {
            usleep(50_000)
        }
        if process.isRunning {
            kill(process.processIdentifier, SIGKILL)
            process.waitUntilExit()
        }
    }
}
