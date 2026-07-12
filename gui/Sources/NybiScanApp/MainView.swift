import AppKit
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

    // The vertical split is USER-OWNED: detailFraction is the bottom (detail)
    // pane's share of the height. It is written ONLY by the drag gesture. The
    // 0.5 default applies once at launch; after that the divider holds wherever
    // the user dragged it. Selection changes the detail pane's CONTENT, never its
    // HEIGHT, so clicking rows never moves the divider.
    @State private var detailFraction: CGFloat = 0.5
    @State private var dragStartFraction: CGFloat?

    private let dividerThickness: CGFloat = 6

    // Re-sort on a throttled cadence (not per WS event): during active capture,
    // entry_updated fires many times per second, and re-sorting the whole table
    // on each would spike CPU.
    private let resortTick = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    var body: some View {
        GeometryReader { geo in
            let available = max(0, geo.size.height - dividerThickness)
            let detailH = min(max(available * detailFraction, 0), available)
            let tableH = available - detailH
            VStack(spacing: 0) {
                tablePane.frame(height: tableH).clipped()
                splitDivider(available: available)
                // DetailView identity is stable; only its content changes on
                // selection. Its height comes from detailFraction, never selection.
                DetailView().frame(height: detailH).clipped()
            }
        }
        .navigationTitle(model.project?.name ?? "NybiScan")
        .onChange(of: selection) { _, newValue in
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

    private var tablePane: some View {
        VStack(spacing: 0) {
            liveHeader
            Divider()
            historyTable
        }
    }

    private func splitDivider(available: CGFloat) -> some View {
        ZStack {
            Color(nsColor: .separatorColor)
            // A subtle grip mark in the middle.
            RoundedRectangle(cornerRadius: 1).fill(Color.secondary.opacity(0.5))
                .frame(width: 28, height: 2)
        }
        .frame(height: dividerThickness)
        .contentShape(Rectangle())
        .onHover { inside in
            if inside { NSCursor.resizeUpDown.set() } else { NSCursor.arrow.set() }
        }
        .gesture(
            DragGesture()
                .onChanged { value in
                    guard available > 0 else { return }
                    let start = dragStartFraction ?? detailFraction
                    if dragStartFraction == nil { dragStartFraction = detailFraction }
                    // Divider up (negative translation) grows the bottom detail.
                    let newDetailH = (start * available) - value.translation.height
                    detailFraction = min(max(newDetailH / available, 0), 1)
                }
                .onEnded { _ in dragStartFraction = nil }
        )
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
