import Foundation

/// WebSocket auth for /ws/history. The token goes in the Authorization header
/// AND the Sec-WebSocket-Protocol subprotocol ("nybiscan, <token>"), never in a
/// query string (query strings leak secrets into logs/history).
public enum WebSocketAuth {
    public static let subprotocolName = "nybiscan"

    public static func makeRequest(port: Int, token: String) -> URLRequest {
        let url = URL(string: "ws://127.0.0.1:\(port)/ws/history")!
        var req = URLRequest(url: url)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("\(subprotocolName), \(token)", forHTTPHeaderField: "Sec-WebSocket-Protocol")
        return req
    }
}

public enum HistoryEventDecoder {
    public static func decode(_ text: String) -> HistoryEvent? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? NybiCoders.makeDecoder().decode(HistoryEvent.self, from: data)
    }
}
