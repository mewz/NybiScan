import Foundation
import NybiScanKit

enum AppPhase: Equatable {
    case starting
    case error(String)
    case needsAck
    case ready
}

enum AppSection: Equatable {
    case history
    case bench
}

/// Editable working copy of a Bench tab's request (port kept as text for the field).
struct BenchDraft: Equatable {
    var rawRequest = ""
    var connHost = ""
    var connPort = ""
    var connTls = true
    var contentLengthAutofill = true
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
    @Published var detailUI = DetailUIState()  // selected row id + persistent active tab
    @Published var detail: HistoryDetail?
    @Published var proxyStatus: ProxyStatus?
    @Published var caInfo: CaInfo?
    @Published var wsConnected = false
    @Published var lastError: String?
    @Published var caNotice: String?  // non-blocking notice, e.g. a new CA was generated

    // Bench
    @Published var section: AppSection = .history
    @Published var benchTabs: [BenchTab] = []
    @Published var selectedBenchTabId: Int?
    @Published var benchDraft = BenchDraft()
    @Published var benchResponse: BenchSendDetail?
    @Published var benchHistory: [BenchSendSummary] = []
    @Published var benchSending = false
    @Published var benchNote: String?  // e.g. dropped-body on seed
    @Published var viewedSendId: Int?  // which prior send the panes currently show (nil = newest)

    private var core: CoreProcess?
    private var client: ControlAPIClient?
    private let apiSession = URLSession(configuration: .ephemeral)
    private let wsSession = URLSession(configuration: .default)
    private var wsTask: Task<Void, Never>?

    var isCoreRunning: Bool { core?.isRunning ?? false }

    // ----- startup -----

    func start() async {
        phase = .starting

        // Remove any stale runtime.json (from a previous core / manual `serve`)
        // BEFORE spawning, so we only ever connect to the port + token our own
        // freshly spawned core writes. A stale file points at a dead port and
        // would make health time out.
        let runtimeURL = RuntimeInfoReader.defaultURL()
        try? FileManager.default.removeItem(at: runtimeURL)

        let proc = CoreProcess()
        do {
            try proc.start()
        } catch CoreProcessError.binaryNotFound {
            // Missing/misnamed repo .venv: a loud, actionable error, not the
            // generic health-timeout symptom.
            phase = .error(CoreProcess.notFoundMessage(binPath: proc.binPath))
            return
        } catch {
            phase = .error("Could not start the core (\(proc.binPath)): \(error)")
            return
        }
        core = proc

        // From here the binary was located and launched; any failure below is a
        // health/startup problem, not a missing core.
        guard let info = await HealthPoller.waitForRuntimeInfo(url: runtimeURL, timeoutSeconds: 10) else {
            phase = .error("The core was launched but did not write runtime.json within 10s (binary: \(proc.binPath)).")
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
        caNotice = nil
        await reloadHistory()
        // Subscribe to live updates BEFORE auto-starting the proxy so the very
        // first captured requests are not missed.
        startWSStream()
        await refreshProxyStatus()
        await refreshCaInfo()
        await loadBench()
        await autoStartProxyIfEnabled()
    }

    // ----- bench ------------------------------------------------------------

    func loadBench() async {
        guard let c = client else { return }
        benchTabs = (try? await c.benchTabs()) ?? []
        if selectedBenchTabId == nil || !benchTabs.contains(where: { $0.id == selectedBenchTabId }) {
            selectedBenchTabId = benchTabs.first?.id
        }
        if let id = selectedBenchTabId {
            await selectBenchTab(id, save: false)
        } else {
            benchDraft = BenchDraft()
            benchResponse = nil
            benchHistory = []
        }
    }

    func newBenchTab() async {
        guard let c = client else { return }
        await saveDraft()
        if let tab = try? await c.createBenchTab(CreateBenchTabPayload()) {
            benchTabs.append(tab)
            await selectBenchTab(tab.id, save: false)
        }
    }

    func selectBenchTab(_ id: Int, save: Bool) async {
        if save { await saveDraft() }
        selectedBenchTabId = id
        benchResponse = nil
        if let tab = benchTabs.first(where: { $0.id == id }) {
            benchDraft = BenchDraft(
                rawRequest: tab.rawRequest, connHost: tab.connHost,
                connPort: String(tab.connPort), connTls: tab.connTls,
                contentLengthAutofill: tab.contentLengthAutofill
            )
            benchNote = tab.droppedNote
        }
        await loadBenchHistory()
    }

    func saveDraft() async {
        guard let c = client, let id = selectedBenchTabId else { return }
        let payload = UpdateBenchTabPayload(
            rawRequest: benchDraft.rawRequest, connHost: benchDraft.connHost,
            connPort: Int(benchDraft.connPort), connTls: benchDraft.connTls,
            contentLengthAutofill: benchDraft.contentLengthAutofill
        )
        if let updated = try? await c.updateBenchTab(id, payload),
           let idx = benchTabs.firstIndex(where: { $0.id == id }) {
            benchTabs[idx] = updated
        }
    }

    func sendBench() async {
        guard let c = client, let id = selectedBenchTabId else { return }
        await saveDraft()
        benchSending = true
        // The send runs off the UI thread (URLSession); the UI stays responsive and
        // shows Cancel. A hang (e.g. wrong Content-Length) is bounded by the core
        // timeout or aborted by Cancel; either way a result is recorded and returned.
        benchResponse = try? await c.benchSend(id)
        benchSending = false
        await loadBenchHistory()
        viewedSendId = benchResponse?.id  // the newest send is now shown
    }

    /// Abort the in-flight send. The outstanding /send returns a recorded "cancelled"
    /// result, which flips benchSending back to idle in sendBench().
    func cancelBench() async {
        guard let c = client, let id = selectedBenchTabId else { return }
        try? await c.benchCancel(id)
    }

    func loadBenchHistory() async {
        guard let c = client, let id = selectedBenchTabId else {
            benchHistory = []
            return
        }
        benchHistory = (try? await c.benchTabHistory(id)) ?? []
    }

    func showBenchSend(_ sendId: Int) async {
        // Load a prior send: show its request snapshot in the editor + its response.
        // Viewing an old entry populates the editor for tweak-and-resend but never
        // mutates the stored snapshot; a later Send appends a NEW entry (linear).
        guard let detail = try? await client?.benchSendDetail(sendId) else { return }
        benchResponse = detail
        viewedSendId = sendId
        benchDraft = BenchDraft(
            rawRequest: detail.reqRaw, connHost: detail.connHost,
            connPort: String(detail.connPort), connTls: detail.connTls,
            contentLengthAutofill: detail.contentLengthAutofill
        )
    }

    /// Step one send older/newer through this tab's history (Burp `<`/`>`). No-op at
    /// an end. `benchHistory` is oldest -> newest as the API returns it.
    func stepBenchHistory(older: Bool) async {
        let ids = benchHistory.map { $0.id }
        let target = older
            ? BenchHistoryNav.older(ids, current: viewedSendId)
            : BenchHistoryNav.newer(ids, current: viewedSendId)
        if let target { await showBenchSend(target) }
    }

    func renameBenchTab(_ id: Int, name: String) async {
        guard let c = client else { return }
        if let updated = try? await c.updateBenchTab(id, UpdateBenchTabPayload(name: name)),
           let idx = benchTabs.firstIndex(where: { $0.id == id }) {
            benchTabs[idx] = updated
        }
    }

    func deleteBenchTab(_ id: Int) async {
        try? await client?.deleteBenchTab(id)
        benchTabs.removeAll { $0.id == id }
        if selectedBenchTabId == id {
            selectedBenchTabId = benchTabs.first?.id
            if let next = selectedBenchTabId {
                await selectBenchTab(next, save: false)
            } else {
                benchDraft = BenchDraft(); benchResponse = nil; benchHistory = []
            }
        }
    }

    func sendToBench(historyId: Int) async {
        guard let c = client else { return }
        await saveDraft()
        if let tab = try? await c.createBenchTab(CreateBenchTabPayload(seedHistoryId: historyId)) {
            benchTabs.append(tab)
            section = .bench
            await selectBenchTab(tab.id, save: false)
        }
    }

    private func autoStartProxyIfEnabled() async {
        guard AutoStart.shouldStart(config), let c = client else { return }
        // A CA absent right now means proxyStart will generate one (untrusted
        // until the user exports + trusts it); notice the generated-now case.
        let caWasMissing = !(caInfo?.exists ?? false)
        let ip = config?.defaultListenIp ?? "127.0.0.1"
        let port = config?.defaultListenPort ?? 8080
        do {
            _ = try await c.proxyStart(ProxyStartPayload(ip: ip, port: port))
        } catch {
            lastError = "Auto-start proxy failed: \(friendly(error))"
            await refreshProxyStatus()
            return
        }
        await refreshProxyStatus()
        await refreshCaInfo()
        if caWasMissing {
            caNotice = "A new CA was generated. Export and trust it (Options -> Export CA certificate) to intercept HTTPS."
        }
    }

    func setAutoStartProxy(_ on: Bool) async {
        guard let c = client else { return }
        config = try? await c.updateConfig(autoStartProxy: on)
    }

    /// Fetch the public CA cert for the GUI to save via its own dialog. Returns
    /// nil (and sets lastError) on failure; the private key never leaves the core.
    func exportCACert(format: String) async -> (data: Data, suggestedName: String)? {
        guard let c = client else { return nil }
        do {
            let export = try await c.exportCA(format: format)
            guard let data = export.certData else {
                lastError = "CA export returned no data"
                return nil
            }
            return (data, export.suggestedFilename)
        } catch {
            lastError = "CA export failed: \(friendly(error))"
            return nil
        }
    }

    func reloadHistory() async {
        guard let c = client else { return }
        if let rows = try? await c.history(limit: 2000) {
            model = HistoryModel(rows)
        }
    }

    // ----- detail -----

    func select(id: Int) async {
        // Update the selected row (tab is preserved by DetailUIState). Do NOT nil
        // detail first: the flap would destroy the detail view and reset its tab
        // and flash the empty state while arrow-scanning.
        detailUI.select(id)
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
                if detailUI.selectedId == event.id { self.detail = detail }
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
