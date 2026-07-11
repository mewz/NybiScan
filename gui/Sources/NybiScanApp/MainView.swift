import SwiftUI
import NybiScanKit

struct MainView: View {
    @EnvironmentObject var model: AppModel
    @State private var selection: Int?
    @State private var showOptions = false
    @State private var sortOrder: [KeyPathComparator<HistorySummary>] = [
        KeyPathComparator(\.id, order: .forward)
    ]
    @State private var sortedRows: [HistorySummary] = []
    @State private var lastCount = -1

    // Re-sort on a throttled cadence (not per WS event): during active capture,
    // entry_updated fires many times per second, and re-sorting the whole table
    // on each would spike CPU.
    private let resortTick = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    var body: some View {
        // Data table on top (full width), inspector detail below (full width),
        // with a draggable vertical divider. This is a data-table + inspector
        // model, not a navigation master-detail sidebar.
        VSplitView {
            VStack(spacing: 0) {
                liveHeader
                Divider()
                historyTable
            }
            .frame(minHeight: 44)  // can squash to a sliver so the detail can dominate

            DetailView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .frame(minHeight: 0)  // can squash to a sliver while scanning the table
        }
        .navigationTitle(model.project?.name ?? "NybiScan")
        .onChange(of: selection) { _, newValue in
            // Selection is by entry id (stable across re-sort), so an open detail
            // stays on the same entry as rows stream in.
            if let id = newValue { Task { await model.select(id: id) } }
        }
        .onChange(of: sortOrder) { _, _ in resort(force: true) }
        .onReceive(resortTick) { _ in resort(force: false) }
        .onAppear { resort(force: true) }
        .toolbar {
            ToolbarItem {
                Button { showOptions = true } label: { Label("Options", systemImage: "gearshape") }
            }
            ToolbarItem {
                Button { Task { await model.reloadHistory(); resort(force: true) } } label: {
                    Label("Reload", systemImage: "arrow.clockwise")
                }
            }
        }
        .sheet(isPresented: $showOptions) { OptionsView() }
    }

    private var liveHeader: some View {
        HStack(spacing: 6) {
            Circle().fill(model.wsConnected ? Color.green : Color.red).frame(width: 8, height: 8)
            Text(model.wsConnected ? "Live" : "Live updates disconnected")
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
            Text("\(model.model.entries.count) requests").font(.caption).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
    }

    private var historyTable: some View {
        // Column widths by importance/content shape. Host and URL flex to absorb
        // extra window width; the narrow fixed columns keep tight widths and never
        // steal room from Host/URL. Host has a hard min floor that fits a full
        // https domain before truncating.
        Table(sortedRows, selection: $selection, sortOrder: $sortOrder) {
            TableColumn("#", value: \.id) { Text("\($0.id)").monospacedDigit() }
                .width(min: 36, ideal: 42, max: 60)
            TableColumn("Host", value: \.host) { row in
                HStack(spacing: 4) {
                    Image(systemName: row.isSecure ? "lock.fill" : "lock.open")
                        .font(.caption2).foregroundStyle(row.isSecure ? .green : .secondary)
                    Text(row.hostDisplay).lineLimit(1)
                }
            }
            .width(min: 220, ideal: 320)  // fits https://www.something.com before clipping
            TableColumn("Method", value: \.method) { Text($0.method) }
                .width(min: 60, ideal: 66, max: 84)
            TableColumn("URL") { Text($0.url).lineLimit(1) }
                .width(min: 240, ideal: 420)  // widest flexible column
            TableColumn("Status", value: \.statusSort) { row in statusCell(row) }
                .width(min: 56, ideal: 60, max: 72)
            TableColumn("Length", value: \.respLength) { row in
                Text(row.respLength > 0 ? "\(row.respLength)" : "").monospacedDigit()
            }
            .width(min: 60, ideal: 70, max: 92)
            TableColumn("MIME") { Text($0.mimeType ?? "") }
                .width(min: 150, ideal: 190, max: 280)  // fits application/javascript
            TableColumn("Ext") { Text($0.extension ?? "") }
                .width(min: 40, ideal: 50, max: 70)
            TableColumn("IP") { Text($0.remoteIp ?? "") }
                .width(min: 118, ideal: 128, max: 140)  // fits 255.255.255.255
            TableColumn("Time", value: \.reqStartTs) { Text(Self.timeString($0.reqStartTs)) }
                .width(min: 72, ideal: 82, max: 96)
        }
    }

    private func statusCell(_ row: HistorySummary) -> some View {
        Group {
            switch row.captureStatus {
            case "pending": Text("pending").foregroundStyle(.orange)
            case "error": Text("error").foregroundStyle(.red)
            default: Text(row.status.map(String.init) ?? "")
            }
        }
    }

    private func resort(force: Bool) {
        let entries = model.model.entries
        // Skip redundant timer-driven sorts when nothing new arrived.
        if !force && entries.count == lastCount { return }
        lastCount = entries.count
        sortedRows = entries.sorted(using: sortOrder)
    }

    private static func timeString(_ epochMs: Int) -> String {
        guard epochMs > 0 else { return "" }
        let date = Date(timeIntervalSince1970: Double(epochMs) / 1000.0)
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: date)
    }
}
