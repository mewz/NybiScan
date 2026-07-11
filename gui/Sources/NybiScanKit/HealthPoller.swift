import Foundation

/// Waits for the core control API to become healthy after spawn. Times out
/// cleanly if the core never comes up, so the GUI shows a clear error instead of
/// hanging.
public enum HealthPoller {
    public static func waitForHealthy(
        client: ControlAPIClient,
        timeoutSeconds: Double,
        intervalSeconds: Double = 0.1
    ) async -> Bool {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        repeat {
            if let health = try? await client.health(), health.status == "ok" {
                return true
            }
            try? await Task.sleep(nanoseconds: UInt64(intervalSeconds * 1_000_000_000))
        } while Date() < deadline
        return false
    }

    /// Waits for runtime.json to appear (the core writes it at startup) and
    /// returns the parsed info, or nil on timeout.
    public static func waitForRuntimeInfo(
        url: URL = RuntimeInfoReader.defaultURL(),
        timeoutSeconds: Double,
        intervalSeconds: Double = 0.1
    ) async -> RuntimeInfo? {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        repeat {
            if let info = try? RuntimeInfoReader.read(from: url) {
                return info
            }
            try? await Task.sleep(nanoseconds: UInt64(intervalSeconds * 1_000_000_000))
        } while Date() < deadline
        return nil
    }
}
