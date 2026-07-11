import SwiftUI
import NybiScanKit

struct DetailView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let d = model.detail {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("\(d.method) \(d.scheme)://\(d.host):\(d.port)\(d.url)")
                        .font(.headline).textSelection(.enabled)

                    GroupBox("Request") {
                        VStack(alignment: .leading, spacing: 6) {
                            RawText(d.reqHeadersRaw)
                            Divider()
                            BodyView(b64: d.reqBodyB64, dropped: d.reqBodyDropped)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GroupBox("Response") {
                        Group {
                            if d.captureStatus == "pending" {
                                HStack { ProgressView().controlSize(.small); Text("Waiting for response...") }
                                    .foregroundStyle(.secondary)
                            } else if d.captureStatus == "error" {
                                Text("Request errored; no response captured.").foregroundStyle(.red)
                            } else {
                                VStack(alignment: .leading, spacing: 6) {
                                    RawText(d.respHeadersRaw)
                                    Divider()
                                    BodyView(b64: d.respBodyB64, dropped: d.respBodyDropped)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding()
            }
        } else {
            Text("Select a request").foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private struct RawText: View {
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
