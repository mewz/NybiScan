import Foundation

public struct ControlAPIError: Error, Sendable, Equatable {
    public let status: Int
    public let body: String
}

/// Thin typed client over the localhost control API. Attaches the bearer token
/// to every request. Holds no business logic: it builds requests, sends them,
/// and decodes typed responses.
public struct ControlAPIClient: Sendable {
    public let port: Int
    public let token: String
    private let session: URLSession

    public init(port: Int, token: String, session: URLSession = .shared) {
        self.port = port
        self.token = token
        self.session = session
    }

    // Exposed for tests: proves the bearer token is attached and the path/method
    // are correct without needing a live server.
    public func makeRequest(_ method: String, _ path: String, body: Data? = nil) -> URLRequest {
        let url = URL(string: "http://127.0.0.1:\(port)\(path)")!
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return req
    }

    private func send<Res: Decodable>(_ method: String, _ path: String, body: Data? = nil) async throws -> Res {
        let (data, response) = try await session.data(for: makeRequest(method, path, body: body))
        try Self.checkStatus(response, data)
        return try NybiCoders.makeDecoder().decode(Res.self, from: data)
    }

    private func sendNoContent(_ method: String, _ path: String, body: Data? = nil) async throws {
        let (data, response) = try await session.data(for: makeRequest(method, path, body: body))
        try Self.checkStatus(response, data)
    }

    private static func checkStatus(_ response: URLResponse, _ data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw ControlAPIError(status: -1, body: "non-http response")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw ControlAPIError(status: http.statusCode, body: String(data: data, encoding: .utf8) ?? "")
        }
    }

    private static func encode(_ value: some Encodable) throws -> Data {
        try NybiCoders.makeEncoder().encode(value)
    }

    // ----- endpoints --------------------------------------------------------

    public func health() async throws -> HealthInfo { try await send("GET", "/health") }

    public func getConfig() async throws -> ConfigInfo { try await send("GET", "/config") }

    public func acknowledge() async throws -> ConfigInfo {
        try await send("POST", "/config/acknowledge")
    }

    public func updateConfig(autoStartProxy: Bool) async throws -> ConfigInfo {
        try await send("POST", "/config", body: try Self.encode(UpdateConfigPayload(autoStartProxy: autoStartProxy)))
    }

    public func exportCA(format: String) async throws -> CaExport {
        try await send("POST", "/ca/export", body: try Self.encode(CaExportPayload(format: format)))
    }

    public func currentProject() async throws -> ProjectInfo {
        try await send("GET", "/projects/current")
    }

    public func createProject(_ payload: CreateProjectPayload) async throws -> ProjectInfo {
        try await send("POST", "/projects", body: try Self.encode(payload))
    }

    public func openProject(_ payload: OpenProjectPayload) async throws -> ProjectInfo {
        try await send("POST", "/projects/open", body: try Self.encode(payload))
    }

    public func history(limit: Int = 500, offset: Int = 0) async throws -> [HistorySummary] {
        try await send("GET", "/history?limit=\(limit)&offset=\(offset)")
    }

    public func historyEntry(id: Int) async throws -> HistoryDetail {
        try await send("GET", "/history/\(id)")
    }

    public func proxyStatus() async throws -> ProxyStatus { try await send("GET", "/proxy/status") }

    public func proxyStart(_ payload: ProxyStartPayload) async throws -> ProxyStatus {
        try await send("POST", "/proxy/start", body: try Self.encode(payload))
    }

    public func proxyStop() async throws { try await sendNoContent("POST", "/proxy/stop") }

    public func caInfo() async throws -> CaInfo { try await send("GET", "/ca/info") }
}
