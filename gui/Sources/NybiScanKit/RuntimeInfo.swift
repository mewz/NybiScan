import Foundation

public enum RuntimeInfoError: Error, Equatable {
    case missing
    case malformed(String)
}

/// Reads {port, token, pid} from the core's runtime.json. Always reads fresh
/// from disk (no caching): the control-API port is auto-picked and changes every
/// launch, so a cached port would connect to the wrong (or a dead) process.
public enum RuntimeInfoReader {
    public static func defaultURL() -> URL {
        let base: URL
        if let override = ProcessInfo.processInfo.environment["NYBISCAN_SUPPORT_DIR"], !override.isEmpty {
            base = URL(fileURLWithPath: override)
        } else {
            base = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/NybiScan")
        }
        return base.appendingPathComponent("runtime.json")
    }

    public static func read(from url: URL = defaultURL()) throws -> RuntimeInfo {
        guard let data = try? Data(contentsOf: url) else {
            throw RuntimeInfoError.missing
        }
        do {
            return try JSONDecoder().decode(RuntimeInfo.self, from: data)
        } catch {
            throw RuntimeInfoError.malformed(String(describing: error))
        }
    }
}
