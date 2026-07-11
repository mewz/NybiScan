import SwiftUI
import NybiScanKit

struct MainView: View {
    @EnvironmentObject var model: AppModel
    @State private var selection: Int?
    @State private var showOptions = false

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                HStack(spacing: 6) {
                    Circle().fill(model.wsConnected ? Color.green : Color.red)
                        .frame(width: 8, height: 8)
                    Text(model.wsConnected ? "Live" : "Live updates disconnected")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text("\(model.model.entries.count)").font(.caption).foregroundStyle(.secondary)
                }
                .padding(.horizontal, 8).padding(.vertical, 6)
                Divider()
                List(model.model.entries, selection: $selection) { row in
                    HistoryRow(row: row)
                }
            }
            .frame(minWidth: 360)
            .navigationTitle(model.project?.name ?? "NybiScan")
            .onChange(of: selection) { _, newValue in
                if let id = newValue { Task { await model.select(id: id) } }
            }
        } detail: {
            DetailView()
        }
        .toolbar {
            ToolbarItem {
                Button { showOptions = true } label: { Label("Options", systemImage: "gearshape") }
            }
            ToolbarItem {
                Button { Task { await model.reloadHistory() } } label: {
                    Label("Reload", systemImage: "arrow.clockwise")
                }
            }
        }
        .sheet(isPresented: $showOptions) { OptionsView() }
    }
}

struct HistoryRow: View {
    let row: HistorySummary

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(row.method).font(.caption).bold()
                Text(row.hostDisplay).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                statusBadge
            }
            Text(row.url).lineLimit(1)
            if let mime = row.mimeType {
                Text("\(mime)  \(row.respLength) bytes").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private var statusBadge: some View {
        Group {
            switch row.captureStatus {
            case "pending": Text("pending").foregroundStyle(.orange)
            case "error": Text("error").foregroundStyle(.red)
            default: Text(row.status.map(String.init) ?? "-").foregroundStyle(.secondary)
            }
        }
        .font(.caption)
    }
}
