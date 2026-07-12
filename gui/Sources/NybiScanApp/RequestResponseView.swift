import AppKit
import SwiftUI
import NybiScanKit

/// Reusable tabbed Request/Response viewer. Read-only in Plan 3; the `editable`
/// flag is reserved so Plan 4 Bench can reuse this SAME component with an editable
/// Request tab. Raw view only for now (Headers/Hex sub-tabs are deferred).
///
/// The raw text is rendered with an NSTextView (RawTextView) rather than a SwiftUI
/// Text in a ScrollView: SwiftUI Text does not get a fresh layout/redraw pass when
/// a very large string is assigned asynchronously, so large bodies rendered blank
/// until a selection/scroll forced a redraw. NSTextView handles large text and we
/// force layout + display on update.
struct RequestResponseView: View {
    let detail: HistoryDetail
    @Binding var tab: DetailTab
    var editable: Bool = false  // reserved for Bench (Plan 4); ignored here

    @State private var requestText = ""
    @State private var responseText = ""

    // Recompute when the entry changes OR when its response arrives
    // (pending -> complete keeps the same id but changes status/body).
    private var loadKey: String {
        "\(detail.id)|\(detail.captureStatus)|\(detail.respBodyB64?.count ?? -1)"
    }

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                Text("Request").tag(DetailTab.request)
                Text("Response").tag(DetailTab.response)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(8)
            Divider()
            content
        }
        .task(id: loadKey) { await load() }
    }

    @ViewBuilder private var content: some View {
        switch tab {
        case .request:
            RawTextView(text: requestText)
        case .response:
            if detail.captureStatus == "pending" {
                centered { HStack { ProgressView().controlSize(.small); Text("Waiting for response...") } }
            } else if detail.captureStatus == "error" {
                centered { Text("Request errored; no response captured.").foregroundStyle(.red) }
            } else {
                RawTextView(text: responseText)
            }
        }
    }

    private func centered<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        content()
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
    }

    private func load() async {
        requestText = detail.reqHeadersRaw + "\n\n"
            + (await Self.decodedBody(detail.reqBodyB64, dropped: detail.reqBodyDropped))
        if detail.captureStatus == "complete" {
            responseText = detail.respHeadersRaw + "\n\n"
                + (await Self.decodedBody(detail.respBodyB64, dropped: detail.respBodyDropped))
        } else {
            responseText = ""
        }
    }

    /// Decodes the base64 body OFF the main thread, truncates very large bodies,
    /// and falls back to a hex preview for non-UTF-8 content. Display only.
    static func decodedBody(_ b64: String?, dropped: Bool) async -> String {
        if dropped { return "[body dropped by the capture filter; metadata retained]" }
        guard let b64 else { return "[no body]" }
        guard let data = Data(base64Encoded: b64) else { return "" }
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

/// A read-only, selectable, scrollable monospaced text view. Unlike SwiftUI Text,
/// it paints large content immediately: on update we set the string and force a
/// full layout + display, so a large body does not stay blank until an interaction.
struct RawTextView: NSViewRepresentable {
    let text: String

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        scroll.hasVerticalScroller = true
        scroll.drawsBackground = false
        if let tv = scroll.documentView as? NSTextView {
            tv.isEditable = false
            tv.isSelectable = true
            tv.isRichText = false
            tv.drawsBackground = false
            tv.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
            tv.textContainerInset = NSSize(width: 8, height: 8)
            tv.textContainer?.widthTracksTextView = true
            tv.isVerticallyResizable = true
        }
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let tv = scroll.documentView as? NSTextView else { return }
        if tv.string != text {
            tv.string = text
            // Force glyph layout + a redraw so the full body paints now, without
            // waiting for a selection/scroll to trigger it.
            if let lm = tv.layoutManager, let tc = tv.textContainer {
                lm.ensureLayout(for: tc)
            }
            tv.needsLayout = true
            tv.needsDisplay = true
        }
    }
}
