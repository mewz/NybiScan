import Foundation

// Codable models that mirror the control API responses exactly. All snake_case
// JSON keys map to camelCase properties via convertFromSnakeCase (see NybiCoders),
// so no CodingKeys boilerplate is needed.

public enum NybiCoders {
    public static func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    public static func makeEncoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }
}

public struct RuntimeInfo: Codable, Sendable, Equatable {
    public let port: Int
    public let token: String
    public let pid: Int?
}

public struct HealthInfo: Codable, Sendable, Equatable {
    public let status: String
    public let version: String
    public let projectOpen: Bool
}

public struct ConfigInfo: Codable, Sendable, Equatable {
    public let authorizedUseAck: Bool
    public let autoStartProxy: Bool
    public let defaultListenIp: String
    public let defaultListenPort: Int
}

public struct CaExport: Codable, Sendable, Equatable {
    public let format: String
    public let suggestedFilename: String
    public let certB64: String

    public var certData: Data? { Data(base64Encoded: certB64) }
}

/// The active tab in the request/response detail. Kept in model state so it
/// persists across row selection (selection changes CONTENT, not the tab).
public enum DetailTab: String, Sendable, Equatable, CaseIterable {
    case request
    case response
}

/// The detail pane's persistent UI state. select() updates the selected row but
/// NEVER changes the active tab, so arrow-key scanning keeps the same tab.
public struct DetailUIState: Sendable, Equatable {
    public var tab: DetailTab = .request
    public private(set) var selectedId: Int?

    public init(tab: DetailTab = .request, selectedId: Int? = nil) {
        self.tab = tab
        self.selectedId = selectedId
    }

    public mutating func select(_ id: Int) {
        selectedId = id  // tab intentionally untouched
    }
}

/// Whether project-open should auto-start the proxy. Decision lives in Kit so it
/// is testable; AppModel calls it and drives the existing proxy-start API.
public enum AutoStart {
    public static func shouldStart(_ config: ConfigInfo?) -> Bool {
        config?.autoStartProxy ?? false
    }
}

public struct ProjectInfo: Codable, Sendable, Equatable {
    public let projectOpen: Bool
    public let path: String?
    public let name: String?
    public let uuid: String?
    public let encrypted: Bool?
    public let recordCount: Int?
    public let proxyRunning: Bool?
}

public struct ProxyStatus: Codable, Sendable, Equatable {
    public let running: Bool
    public let listenHost: String?
    public let listenPort: Int?
    public let caDir: String?
    public let sslInsecure: Bool?
}

public struct CaInfo: Codable, Sendable, Equatable {
    public let scope: String
    public let exists: Bool
    public let confdir: String?
    public let cn: String?
    public let fingerprintSha256: String?
    public let notAfter: String?
}

public struct HistorySummary: Codable, Sendable, Equatable, Identifiable {
    public let id: Int
    public let flowId: String?
    public let scheme: String
    public let host: String
    public let port: Int
    public let method: String
    public let url: String
    public let `extension`: String?  // Swift keyword; core-derived file extension
    public let status: Int?
    public let mimeType: String?
    public let respLength: Int
    public let remoteIp: String?
    public let captureStatus: String
    public let reqStartTs: Int
    public let respCompleteTs: Int?
    public let source: String?  // "browser" (proxy) or "spider" (crawl)

    public init(
        id: Int, flowId: String?, scheme: String, host: String, port: Int,
        method: String, url: String, `extension`: String?, status: Int?,
        mimeType: String?, respLength: Int, remoteIp: String?, captureStatus: String,
        reqStartTs: Int, respCompleteTs: Int?, source: String? = nil
    ) {
        self.id = id
        self.flowId = flowId
        self.scheme = scheme
        self.host = host
        self.port = port
        self.method = method
        self.url = url
        self.`extension` = `extension`
        self.status = status
        self.mimeType = mimeType
        self.respLength = respLength
        self.remoteIp = remoteIp
        self.captureStatus = captureStatus
        self.reqStartTs = reqStartTs
        self.respCompleteTs = respCompleteTs
        self.source = source
    }

    /// A lightweight placeholder row built from an entry_created event, which
    /// carries only a subset of fields (no mime/length/extension/timestamps yet).
    public static func pending(from event: HistoryEvent) -> HistorySummary {
        HistorySummary(
            id: event.id, flowId: event.flowId, scheme: "", host: event.host,
            port: 0, method: event.method, url: event.url, extension: nil,
            status: event.status, mimeType: nil, respLength: 0, remoteIp: nil,
            captureStatus: event.captureStatus, reqStartTs: 0, respCompleteTs: nil
        )
    }

    public var hostDisplay: String {
        scheme.isEmpty ? host : "\(scheme)://\(host):\(port)"
    }

    /// Client-side display derivation (thin-client rule): does the URL carry a
    /// query string. Trivial, nothing downstream queries it, so no core field.
    public var hasParams: Bool { url.contains("?") }

    /// Sortable status key (Optional is not Comparable): pending/no-status sorts low.
    public var statusSort: Int { status ?? -1 }

    public var isSecure: Bool { scheme == "https" }
}

public struct HistoryDetail: Codable, Sendable, Equatable {
    public let id: Int
    public let flowId: String?
    public let scheme: String
    public let host: String
    public let port: Int
    public let method: String
    public let url: String
    public let `extension`: String?
    public let status: Int?
    public let mimeType: String?
    public let respLength: Int
    public let remoteIp: String?
    public let captureStatus: String
    public let reqStartTs: Int
    public let respCompleteTs: Int?
    public let reqHeadersRaw: String
    public let reqMimeType: String?
    public let reqBodyB64: String?
    public let reqBodyDropped: Bool
    public let reqContentEncoding: String?
    public let respHeadersRaw: String
    public let respBodyB64: String?
    public let respBodyDropped: Bool
    public let respContentEncoding: String?

    public var summary: HistorySummary {
        HistorySummary(
            id: id, flowId: flowId, scheme: scheme, host: host, port: port,
            method: method, url: url, extension: `extension`, status: status,
            mimeType: mimeType, respLength: respLength, remoteIp: remoteIp,
            captureStatus: captureStatus, reqStartTs: reqStartTs, respCompleteTs: respCompleteTs
        )
    }
}

public struct HistoryEvent: Codable, Sendable, Equatable {
    public let type: String  // entry_created | entry_updated
    public let id: Int
    public let flowId: String?
    public let host: String
    public let method: String
    public let url: String
    public let status: Int?
    public let captureStatus: String
}

// Request payloads (camelCase -> snake_case on encode).

public struct CreateProjectPayload: Encodable, Sendable {
    public let path: String
    public let name: String?
    public let scope: [String]
    public let passphrase: String?
    public init(path: String, name: String?, scope: [String] = [], passphrase: String?) {
        self.path = path; self.name = name; self.scope = scope; self.passphrase = passphrase
    }
}

public struct OpenProjectPayload: Encodable, Sendable {
    public let path: String
    public let passphrase: String?
    public init(path: String, passphrase: String?) { self.path = path; self.passphrase = passphrase }
}

public struct ProxyStartPayload: Encodable, Sendable {
    public let ip: String?
    public let port: Int?
    public let sslInsecure: Bool
    public init(ip: String?, port: Int?, sslInsecure: Bool = false) {
        self.ip = ip; self.port = port; self.sslInsecure = sslInsecure
    }
}

public struct UpdateConfigPayload: Encodable, Sendable {
    public let autoStartProxy: Bool?
    public init(autoStartProxy: Bool?) { self.autoStartProxy = autoStartProxy }
}

public struct CaExportPayload: Encodable, Sendable {
    public let format: String
    public init(format: String) { self.format = format }
}

// ----- Bench (Repeater analog) ----------------------------------------------

public struct BenchTab: Codable, Sendable, Equatable, Identifiable {
    public let id: Int
    public let name: String
    public let orderIndex: Int
    public let rawRequest: String
    public let connHost: String
    public let connPort: Int
    public let connTls: Bool
    public let contentLengthAutofill: Bool
    public let droppedNote: String?  // set on seed when the captured body was dropped
}

public struct BenchSendSummary: Codable, Sendable, Equatable, Identifiable {
    public let id: Int
    public let tabId: Int
    public let status: Int?
    public let respLength: Int
    public let mimeType: String?
    public let error: String?
    public let sentTs: Int
    public let durationMs: Int
}

public struct BenchSendDetail: Codable, Sendable, Equatable {
    public let id: Int
    public let tabId: Int
    public let status: Int?
    public let respLength: Int
    public let mimeType: String?
    public let error: String?
    public let sentTs: Int
    public let durationMs: Int
    public let reqRaw: String
    public let connHost: String
    public let connPort: Int
    public let connTls: Bool
    public let contentLengthAutofill: Bool
    public let respHeadersRaw: String
    public let respBodyB64: String?
    public let respContentEncoding: String?
}

public struct CreateBenchTabPayload: Encodable, Sendable {
    public let name: String?
    public let seedHistoryId: Int?
    public init(name: String? = nil, seedHistoryId: Int? = nil) {
        self.name = name; self.seedHistoryId = seedHistoryId
    }
}

public struct UpdateBenchTabPayload: Encodable, Sendable {
    public let name: String?
    public let orderIndex: Int?
    public let rawRequest: String?
    public let connHost: String?
    public let connPort: Int?
    public let connTls: Bool?
    public let contentLengthAutofill: Bool?
    public init(name: String? = nil, orderIndex: Int? = nil, rawRequest: String? = nil,
                connHost: String? = nil, connPort: Int? = nil, connTls: Bool? = nil,
                contentLengthAutofill: Bool? = nil) {
        self.name = name; self.orderIndex = orderIndex; self.rawRequest = rawRequest
        self.connHost = connHost; self.connPort = connPort; self.connTls = connTls
        self.contentLengthAutofill = contentLengthAutofill
    }
}

// ----- Plan 5: scope, site-map, spider -------------------------------------

public struct ScopeHost: Codable, Sendable, Equatable, Identifiable {
    public let id: Int?
    public let host: String
    public let note: String?
    public let headers: String?
    public var identity: String { host }  // stable id for lists
}

public struct ScopeAddPayload: Encodable, Sendable {
    public let host: String
    public let note: String?
    public let headers: String?
    public init(host: String, note: String? = nil, headers: String? = nil) {
        self.host = host; self.note = note; self.headers = headers
    }
}

public struct ScopeUpdatePayload: Encodable, Sendable {
    public let headers: String?
    public init(headers: String?) { self.headers = headers }
}

/// One path node in a host's site-map tree. Recursive via `children`.
public struct SitemapNode: Codable, Sendable, Equatable, Identifiable {
    public let name: String
    public let fullPath: String
    public let entryIds: [Int]
    public let methods: [String]
    public let statuses: [Int]
    public let sources: [String]
    public let children: [SitemapNode]
    public var id: String { fullPath }
}

public struct SitemapHost: Codable, Sendable, Equatable, Identifiable {
    public let scheme: String
    public let host: String
    public let port: Int
    public let entryCount: Int
    public let root: SitemapNode
    public var id: String { "\(scheme)://\(host):\(port)" }
}

public struct SpiderStatus: Codable, Sendable, Equatable {
    public let running: Bool
    public let found: Int
    public let saved: Int
    public let cap: Int
    public let current: String?
    public let runId: String?
}

public struct SpiderExclude: Codable, Sendable, Equatable, Identifiable {
    public var pattern: String
    public var isRegex: Bool
    public var id = UUID()
    public init(pattern: String, isRegex: Bool = false) {
        self.pattern = pattern; self.isRegex = isRegex
    }
    // The API exchanges only pattern + is_regex; id is a client-side list key.
    enum CodingKeys: String, CodingKey { case pattern; case isRegex }
}

public struct SpiderStartPayload: Encodable, Sendable {
    public let seedHistoryId: Int
    public let maxDepth: Int
    public let exclude: [SpiderExclude]?
    public let rateLimitMs: Int
    public let maxRequests: Int
    public let includeBinary: Bool
    public init(seedHistoryId: Int, maxDepth: Int = 3, exclude: [SpiderExclude]? = nil,
                rateLimitMs: Int = 500, maxRequests: Int = 300, includeBinary: Bool = false) {
        self.seedHistoryId = seedHistoryId; self.maxDepth = maxDepth; self.exclude = exclude
        self.rateLimitMs = rateLimitMs; self.maxRequests = maxRequests
        self.includeBinary = includeBinary
    }
}
