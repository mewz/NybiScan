import SwiftUI
import NybiScanKit

/// Bench (Repeater analog): craft/edit/send a raw request, multiple renamable
/// tabs, per-tab send history. Thin client: all sending/storage is in the core.
struct BenchView: View {
    @EnvironmentObject var model: AppModel
    @State private var renameTab: BenchTab?
    @State private var renameText = ""

    var body: some View {
        VSplitView {
            requestSide.frame(minHeight: 160)
            responseSide.frame(minHeight: 0)
        }
        .toolbar { sectionPicker }
        .task { if model.benchTabs.isEmpty { await model.loadBench() } }
        .onDisappear { Task { await model.saveDraft() } }
        .alert("Rename tab", isPresented: Binding(get: { renameTab != nil }, set: { if !$0 { renameTab = nil } })) {
            TextField("Name", text: $renameText)
            Button("Rename") {
                if let t = renameTab { Task { await model.renameBenchTab(t.id, name: renameText) } }
                renameTab = nil
            }
            Button("Cancel", role: .cancel) { renameTab = nil }
        }
    }

    private var sectionPicker: some ToolbarContent {
        ToolbarItem(placement: .principal) {
            Picker("", selection: $model.section) {
                Text("History").tag(AppSection.history)
                Text("Bench").tag(AppSection.bench)
            }
            .pickerStyle(.segmented).frame(width: 180)
        }
    }

    // ----- request side -----

    private var requestSide: some View {
        VStack(spacing: 0) {
            tabBar
            Divider()
            connectionBar
            if let note = model.benchNote {
                Text(note).font(.caption).foregroundStyle(.orange)
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Divider()
            EditableRawTextView(text: $model.benchDraft.rawRequest)
        }
    }

    private var tabBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(model.benchTabs) { tab in
                    let selected = tab.id == model.selectedBenchTabId
                    Text(tab.name)
                        .font(.caption)
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(selected ? Color.accentColor.opacity(0.25) : Color.gray.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .onTapGesture { Task { await model.selectBenchTab(tab.id, save: true) } }
                        .contextMenu {
                            Button("Rename...") { renameTab = tab; renameText = tab.name }
                            Button("Close", role: .destructive) { Task { await model.deleteBenchTab(tab.id) } }
                        }
                }
                Button { Task { await model.newBenchTab() } } label: { Image(systemName: "plus") }
                    .buttonStyle(.borderless)
            }
            .padding(.horizontal, 8).padding(.vertical, 6)
        }
    }

    private var connectionBar: some View {
        HStack(spacing: 8) {
            Toggle("HTTPS", isOn: $model.benchDraft.connTls).toggleStyle(.checkbox)
            TextField("host", text: $model.benchDraft.connHost).frame(minWidth: 140)
            Text(":").foregroundStyle(.secondary)
            TextField("port", text: $model.benchDraft.connPort).frame(width: 64)
            Toggle("Auto C-L", isOn: $model.benchDraft.contentLengthAutofill).toggleStyle(.checkbox)
            Spacer()
            // While a send is outstanding the button becomes Cancel (with a spinner)
            // so a slow/hanging send stays responsive and recoverable.
            if model.benchSending {
                Button(role: .destructive) { Task { await model.cancelBench() } } label: {
                    HStack(spacing: 5) { ProgressView().controlSize(.small); Text("Cancel") }
                }
            } else {
                Button("Send") { Task { await model.sendBench() } }
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(model.selectedBenchTabId == nil)
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
    }

    // ----- response side -----

    private var responseSide: some View {
        VStack(spacing: 0) {
            responseHeader
            Divider()
            BenchResponseView(detail: model.benchResponse)
        }
    }

    private var responseHeader: some View {
        HStack(spacing: 8) {
            if let r = model.benchResponse {
                if let err = r.error {
                    Text("failed").foregroundStyle(.red).font(.caption)
                    Text(err).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                } else {
                    Text(r.status.map { "\($0)" } ?? "-").font(.caption).bold()
                    Text("\(r.respLength) bytes  \(r.durationMs) ms").font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text("Response").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            historyNav
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
    }

    // Burp Repeater-style history navigation: `<`/`>` step one send at a time, and
    // the dropdown on the `<` control jumps directly to any prior send (newest ->
    // oldest). Selecting a send restores BOTH panes (request editor + response).
    @ViewBuilder private var historyNav: some View {
        if !model.benchHistory.isEmpty {
            let ids = model.benchHistory.map { $0.id }
            let hasOlder = BenchHistoryNav.older(ids, current: model.viewedSendId) != nil
            let hasNewer = BenchHistoryNav.newer(ids, current: model.viewedSendId) != nil
            HStack(spacing: 4) {
                Menu {
                    // Windowed to 25 (a DISPLAY cap; all sends stay stored and
                    // reachable via the arrows). The window slides to always contain
                    // the current position, so #1 stays visible when sitting near the
                    // old end. Labels are per-tab ordinals (1..N), not global ids.
                    let current = model.viewedSendId
                        .flatMap { id in model.benchHistory.firstIndex(where: { $0.id == id }) }
                        ?? (model.benchHistory.count - 1)
                    ForEach(BenchHistoryNav.windowIndices(count: model.benchHistory.count, current: current), id: \.self) { i in
                        let h = model.benchHistory[i]
                        Button(Self.entryLabel(ordinal: BenchHistoryNav.ordinal(index: i), h)) {
                            Task { await model.showBenchSend(h.id) }
                        }
                    }
                } label: {
                    Image(systemName: "chevron.left")
                } primaryAction: {
                    Task { await model.stepBenchHistory(older: true) }
                }
                .menuStyle(.borderlessButton).fixedSize()
                .disabled(!hasOlder && model.benchHistory.count <= 1)
                // SwiftUI/AppKit caches a Menu's built content (and its item action
                // closures); without a changing identity the dropdown keeps a stale
                // list after new sends and selection sticks on the first pick. Re-key
                // on the history content + current selection so it rebuilds live.
                .id("bench-menu-\(model.benchHistory.count)-\(model.benchHistory.last?.id ?? -1)-\(model.viewedSendId ?? -1)")

                Text(Self.positionLabel(ids, current: model.viewedSendId))
                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()

                Button { Task { await model.stepBenchHistory(older: false) } } label: {
                    Image(systemName: "chevron.right")
                }
                .buttonStyle(.borderless).disabled(!hasNewer)
            }
        }
    }

    private static func entryLabel(ordinal: Int, _ h: BenchSendSummary) -> String {
        let outcome = h.status.map(String.init) ?? (h.error ?? "-")
        return "\(ordinal)  \(outcome)"
    }

    private static func positionLabel(_ ids: [Int], current: Int?) -> String {
        let cur = current ?? ids.last
        guard let cur, let idx = ids.firstIndex(of: cur) else { return "" }
        // Per-tab ordinal of the viewed send (1 = first/oldest), matching the
        // dropdown labels. N is this tab's total send count.
        return "\(BenchHistoryNav.ordinal(index: idx))/\(ids.count)"
    }
}

private struct BenchResponseView: View {
    let detail: BenchSendDetail?
    @State private var rendered = ""

    var body: some View {
        Group {
            if let d = detail {
                if let err = d.error {
                    Text("Send failed: \(err)").foregroundStyle(.red)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).padding()
                } else {
                    RawTextView(text: rendered)
                }
            } else {
                Text("No response yet. Edit the request and press Send (Cmd-Return).")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: detail?.id) { rendered = await Self.render(detail) }
    }

    static func render(_ d: BenchSendDetail?) async -> String {
        guard let d, d.error == nil else { return "" }
        let body = await RequestResponseView.decodedBody(d.respBodyB64, dropped: false)
        return d.respHeadersRaw + "\n" + body
    }
}
