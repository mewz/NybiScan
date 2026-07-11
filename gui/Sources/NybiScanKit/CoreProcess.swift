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

    /// Resolve the core binary. Overridable via NYBISCAN_BIN; otherwise the repo
    /// venv console script relative to the working dir (repo-dev launch only; a
    /// distributed .app must set NYBISCAN_BIN, see DECISIONS.md).
    public static func defaultBinPath() -> String {
        if let override = ProcessInfo.processInfo.environment["NYBISCAN_BIN"], !override.isEmpty {
            return override
        }
        return FileManager.default.currentDirectoryPath + "/.venv/bin/nybiscan"
    }

    public var isRunning: Bool { process.isRunning }
    public var pid: Int32 { process.processIdentifier }

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
