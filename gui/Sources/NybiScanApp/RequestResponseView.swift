import SwiftUI
import NybiScanKit

/// Reusable tabbed Request/Response viewer. Read-only in Plan 3; the `editable`
/// flag is reserved so Plan 4 Bench can reuse this SAME component with an editable
/// Request tab and the resulting Response. Raw view only for now (Headers/Hex
/// sub-tabs are deferred).
struct RequestResponseView: View {
    enum Side: String, CaseIterable, Identifiable {
        case request = "Request"
        case response = "Response"
        var id: String { rawValue }
    }

    let detail: HistoryDetail
    var editable: Bool = false  // reserved for Bench (Plan 4); ignored here

    @State private var side: Side = .request

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $side) {
                ForEach(Side.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(8)
            Divider()
            ScrollView {
                switch side {
                case .request: requestRaw
                case .response: responseRaw
                }
            }
        }
    }

    private var requestRaw: some View {
        VStack(alignment: .leading, spacing: 6) {
            RawText(detail.reqHeadersRaw)
            Divider()
            BodyView(b64: detail.reqBodyB64, dropped: detail.reqBodyDropped)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
    }

    @ViewBuilder private var responseRaw: some View {
        if detail.captureStatus == "pending" {
            HStack { ProgressView().controlSize(.small); Text("Waiting for response...") }
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
        } else if detail.captureStatus == "error" {
            Text("Request errored; no response captured.")
                .foregroundStyle(.red)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
        } else {
            VStack(alignment: .leading, spacing: 6) {
                RawText(detail.respHeadersRaw)
                Divider()
                BodyView(b64: detail.respBodyB64, dropped: detail.respBodyDropped)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
    }
}

struct RawText: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.isEmpty ? "[no headers]" : text)
            .font(.system(.caption, design: .monospaced))
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Decodes the base64 body OFF the main thread, truncates very large bodies, and
/// falls back to a hex preview for non-UTF-8 content. Display handling only.
struct BodyView: View {
    let b64: String?
    let dropped: Bool
    @State private var rendered: String = ""

    var body: some View {
        Group {
            if dropped {
                Text("[body dropped by the capture filter; metadata retained]")
                    .italic().foregroundStyle(.secondary)
            } else if b64 == nil {
                Text("[no body]").italic().foregroundStyle(.secondary)
            } else {
                Text(rendered)
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .task(id: b64) { rendered = await Self.decode(b64) }
    }

    static func decode(_ b64: String?) async -> String {
        guard let b64, let data = Data(base64Encoded: b64) else { return "" }
        return await Task.detached(priority: .utility) { () -> String in
            let cap = 512 * 1024
            let slice = data.count > cap ? data.prefix(cap) : data
            if let text = String(data: slice, encoding: .utf8) {
                return data.count > cap
                    ? text + "\n\n[truncated \(data.count - cap) more bytes]"
                    : text
            }
            let hex = slice.prefix(4096).map { String(format: "%02x", $0) }.joined()
            return "[binary, \(data.count) bytes; hex preview]\n" + hex
        }.value
    }
}
