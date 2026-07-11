import Foundation
import NybiScanKit

enum AppPhase: Equatable {
    case starting
    case error(String)
    case needsAck
    case ready
}

/// Orchestrates the GUI: spawns the core, waits for it, then drives everything
/// through the control API. Holds UI state only; all app logic lives in the core.
@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    @Published var phase: AppPhase = .starting
    @Published var config: ConfigInfo?
    @Published var project: ProjectInfo?
    @Published var model = HistoryModel()
    @Published var selectedEntryID: Int?
    @Published var detail: HistoryDetail?
    @Published var proxyStatus: ProxyStatus?
    @Published var caInfo: CaInfo?
    @Published var wsConnected = false
    @Published var lastError: String?

    private var core: CoreProcess?
    private var client: ControlAPIClient?
    private let apiSession = URLSession(configuration: .ephemeral)
    private let wsSession = URLSession(configuration: .default)
    private var wsTask: Task<Void, Never>?

    var isCoreRunning: Bool { core?.isRunning ?? false }

    // ----- startup -----

    func start() async {
        phase = .starting
        let proc = CoreProcess()
        do {
            try proc.start()
        } catch {
            phase = .error("Could not start the core at \(proc.binPath). Set NYBISCAN_BIN to the nybiscan binary. (\(error))")
            return
        }
        core = proc

        guard let info = await HealthPoller.waitForRuntimeInfo(timeoutSeconds: 10) else {
            phase = .error("The core did not write runtime.json within 10s.")
            return
        }
        let c = ControlAPIClient(port: info.port, token: info.token, session: apiSession)
        guard await HealthPoller.waitForHealthy(client: c, timeoutSeconds: 10) else {
            phase = .error("The core control API did not become healthy within 10s.")
            return
        }
        client = c
        do {
            let cfg = try await c.getConfig()
            config = cfg
            phase = cfg.authorizedUseAck ? .ready : .needsAck
        } catch {
            phase = .error("Failed to read config: \(error)")
        }
    }

    func acknowledge() async {
        guard let c = client else { return }
        do {
            config = try await c.acknowledge()
            phase = .ready
        } catch {
            lastError = "\(error)"
        }
    }

    // ----- projects -----

    func createProject(path: String, name: String, passphrase: String?) async {
        guard let c = client else { return }
        do {
            let info = try await c.createProject(
                CreateProjectPayload(path: path, name: name.isEmpty ? nil : name, passphrase: passphrase)
            )
            await afterProjectOpen(info)
        } catch {
            lastError = friendly(error)
        }
    }

    func openProject(path: String, passphrase: String?) async {
        guard let c = client else { return }
        do {
            let info = try await c.openProject(OpenProjectPayload(path: path, passphrase: passphrase))
            await afterProjectOpen(info)
        } catch {
            lastError = friendly(error)
        }
    }

    private func afterProjectOpen(_ info: ProjectInfo) async {
        project = info
        lastError = nil
        await reloadHistory()
        await refreshProxyStatus()
        await refreshCaInfo()
        startWSStream()
    }

    func reloadHistory() async {
        guard let c = client else { return }
        if let rows = try? await c.history(limit: 2000) {
            model = HistoryModel(rows)
        }
    }

    // ----- detail -----

    func select(id: Int) async {
        selectedEntryID = id
        detail = nil
        detail = try? await client?.historyEntry(id: id)
    }

    // ----- proxy + ca -----

    func proxyStart(ip: String, port: Int) async {
        guard let c = client else { return }
        do {
            _ = try await c.proxyStart(ProxyStartPayload(ip: ip.isEmpty ? nil : ip, port: port))
        } catch {
            lastError = friendly(error)
        }
        await refreshProxyStatus()
    }

    func proxyStop() async {
        try? await client?.proxyStop()
        await refreshProxyStatus()
    }

    func refreshProxyStatus() async {
        proxyStatus = try? await client?.proxyStatus()
    }

    func refreshCaInfo() async {
        caInfo = try? await client?.caInfo()
    }

    // ----- live stream -----

    private func startWSStream() {
        wsTask?.cancel()
        // Fresh runtime.json read: the port is auto-picked and may have changed.
        guard let info = try? RuntimeInfoReader.read() else { return }
        wsTask = Task { [weak self] in
            await self?.runWSLoop(port: info.port, token: info.token)
        }
    }

    private func runWSLoop(port: Int, token: String) async {
        while !Task.isCancelled {
            let task = wsSession.webSocketTask(with: WebSocketAuth.makeRequest(port: port, token: token))
            task.resume()
            wsConnected = true
            do {
                while !Task.isCancelled {
                    let message = try await task.receive()
                    if case let .string(text) = message, let event = HistoryEventDecoder.decode(text) {
                        await handle(event)
                    }
                }
            } catch {
                wsConnected = false
            }
            task.cancel(with: .goingAway, reason: nil)
            if Task.isCancelled { break }
            // Brief backoff before a reconnect attempt; the indicator shows stale.
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
        wsConnected = false
    }

    private func handle(_ event: HistoryEvent) async {
        switch event.type {
        case "entry_created":
            model.insertPending(from: event)
        case "entry_updated":
            if let detail = try? await client?.historyEntry(id: event.id) {
                model.upsert(detail.summary)
                if selectedEntryID == event.id { self.detail = detail }
            }
        default:
            break
        }
    }

    // ----- shutdown -----

    /// Called on app termination (main thread). SIGTERM lets the core drain +
    /// checkpoint; CoreProcess escalates to SIGKILL if needed. No orphan.
    func shutdownSync() {
        wsTask?.cancel()
        core?.terminate()
    }

    private func friendly(_ error: Error) -> String {
        if let api = error as? ControlAPIError {
            return "Server error \(api.status): \(api.body)"
        }
        return "\(error)"
    }
}
