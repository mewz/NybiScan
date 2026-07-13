import SwiftUI
import NybiScanKit

/// A unified site-map tree item: a host is a top-level collapsible folder, and each
/// path (including the index "/") is a node under it. A directly-fetched path carries
/// its own entry_ids (and can be seeded/hidden), even when it also has children.
struct MapItem: Identifiable {
    let id: String
    let title: String
    let entryIds: [Int]
    let sources: [String]
    let isHost: Bool
    let scheme: String
    let host: String
    let port: Int
    let path: String?   // nil = the whole host
    var children: [MapItem]?
}

private func mapNode(_ h: SitemapHost, _ n: SitemapNode) -> MapItem {
    let kids = n.children.map { mapNode(h, $0) }
    return MapItem(id: h.id + n.fullPath, title: n.name, entryIds: n.entryIds,
                   sources: n.sources, isHost: false, scheme: h.scheme, host: h.host,
                   port: h.port, path: n.fullPath, children: kids.isEmpty ? nil : kids)
}

private func buildMapItems(_ hosts: [SitemapHost]) -> [MapItem] {
    hosts.map { h in
        var kids: [MapItem] = []
        // The index "/" shows as its own node when the root was fetched directly.
        if !h.root.entryIds.isEmpty {
            kids.append(MapItem(id: h.id + "/", title: "/", entryIds: h.root.entryIds,
                                sources: h.root.sources, isHost: false, scheme: h.scheme,
                                host: h.host, port: h.port, path: "/", children: nil))
        }
        kids.append(contentsOf: h.root.children.map { mapNode(h, $0) })
        return MapItem(id: h.id, title: "\(h.scheme)://\(h.host):\(Formatting.port(h.port))",
                       entryIds: [], sources: [], isHost: true, scheme: h.scheme,
                       host: h.host, port: h.port, path: nil,
                       children: kids.isEmpty ? nil : kids)
    }
}

/// Dashboard: passive site-map + scope management + live spider status. Thin client:
/// all crawling/scope/hide logic is in the core.
struct DashboardView: View {
    @EnvironmentObject var model: AppModel
    @State private var newScopeHost = ""

    var body: some View {
        VStack(spacing: 0) {
            if let s = model.spiderStatus { spiderBar(s); Divider() }
            HSplitView {
                sitemapPane.frame(minWidth: 320)
                scopePane.frame(minWidth: 240)
            }
            Divider()
            DetailView().frame(minHeight: 150)  // selected path's entry (read-only)
        }
        .task { await model.loadSitemap(); await model.loadScope() }
    }

    // ----- spider status strip -----

    private func spiderBar(_ s: SpiderStatus) -> some View {
        HStack(spacing: 10) {
            if s.running { ProgressView().controlSize(.small) }
            Text(s.running ? "Spidering..." : "Spider idle").font(.caption).bold()
            Text("found \(s.found) / saved \(s.saved)  (cap \(s.cap))")
                .font(.caption).foregroundStyle(.secondary).monospacedDigit()
            if let cur = s.current { Text(cur).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
            Spacer()
            if s.running {
                Button("Stop") { Task { await model.stopSpider() } }
            } else {
                Button("Refresh Map") { Task { await model.loadSitemap() } }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
    }

    // ----- site-map tree (host = collapsible folder) -----

    private var sitemapPane: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Site map").font(.caption).bold()
                Spacer()
                Button { Task { await model.loadSitemap() } } label: { Image(systemName: "arrow.clockwise") }
                    .buttonStyle(.borderless)
            }
            .padding(.horizontal, 8).padding(.vertical, 6)
            Divider()
            if model.sitemap.isEmpty {
                Text("No history mapped yet.").foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    OutlineGroup(buildMapItems(model.sitemap), children: \.children) { item in
                        nodeRow(item)
                    }
                }
            }
        }
    }

    private func nodeRow(_ item: MapItem) -> some View {
        HStack(spacing: 6) {
            Image(systemName: item.isHost ? "network" : (item.children != nil ? "folder" : "doc.text"))
                .font(.caption2).foregroundStyle(.secondary)
            Text(item.title).lineLimit(1)
            if item.sources.contains("spider") {
                Text("spider").font(.caption2).foregroundStyle(.orange)
            }
            Spacer()
            if !item.entryIds.isEmpty {
                Text(verbatim: "\(item.entryIds.count)").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if let id = item.entryIds.first { Task { await model.select(id: id) } }
        }
        .contextMenu {
            if let id = item.entryIds.first {
                Button("Spider from This") { Task { await model.prepareSpider(fromEntryId: id) } }
            }
            Button("Delete (hide from map)", role: .destructive) {
                Task { await model.hideMapNode(scheme: item.scheme, host: item.host,
                                               port: item.port, path: item.path) }
            }
        }
    }

    // ----- scope panel -----

    private var scopePane: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Scope").font(.caption).bold()
                .padding(.horizontal, 8).padding(.vertical, 6)
            Divider()
            if model.scopeHosts.isEmpty {
                Text("No hosts in scope. Right-click a request -> Add to Scope, or add one below.")
                    .font(.caption).foregroundStyle(.secondary).padding(8)
            }
            List(model.scopeHosts) { h in
                HStack(spacing: 6) {
                    Text(h.host).lineLimit(1)
                    if h.headers != nil {
                        Image(systemName: "person.badge.key").font(.caption2).foregroundStyle(.green)
                            .help("Has a stored session")
                    }
                    Spacer()
                    Button(role: .destructive) { Task { await model.removeScope(h.host) } } label: {
                        Image(systemName: "trash")
                    }.buttonStyle(.borderless)
                }
            }
            Divider()
            HStack {
                TextField("host to add", text: $newScopeHost)
                    .onSubmit { addScope() }
                Button("Add") { addScope() }.disabled(newScopeHost.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(8)
        }
    }

    private func addScope() {
        let host = newScopeHost
        newScopeHost = ""
        Task { await model.addScope(host: host) }
    }
}

/// Start-confirmation for a crawl (Burp's config step). Shows the full config and
/// requires explicit approval; the seed host is shown. Presented by SectionContainer
/// so it works from any tab.
struct SpiderStartSheet: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        // Force-unwrap is safe: the sheet is only presented while spiderDraft != nil.
        let draft = Binding(get: { model.spiderDraft ?? SpiderDraft() },
                            set: { model.spiderDraft = $0 })
        VStack(alignment: .leading, spacing: 12) {
            Text("Spider from a captured request").font(.title3.bold())
            Text("Seed host: \(draft.wrappedValue.seedHost)")
                .font(.callout).foregroundStyle(.secondary)
            Text("Crawls only IN-SCOPE hosts, from the seed path downward, using each host's stored session.")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)

            Form {
                Stepper("Max depth: \(draft.wrappedValue.maxDepth)", value: draft.maxDepth, in: 1...20)
                HStack {
                    Text("Rate limit (ms)")
                    TextField("", value: draft.rateLimitMs, format: .number).frame(width: 80)
                }
                HStack {
                    Text("Max requests (cap)")
                    TextField("", value: draft.maxRequests, format: .number).frame(width: 80)
                }
                Toggle("Include binary resources", isOn: draft.includeBinary)
                excludeEditor(draft)
            }

            HStack {
                Spacer()
                Button("Cancel") { model.spiderDraft = nil }
                Button("Start Spider") { Task { await model.startSpider() } }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16).frame(width: 480)
    }

    @ViewBuilder
    private func excludeEditor(_ draft: Binding<SpiderDraft>) -> some View {
        Section("Exclude (never fetched)") {
            ForEach(draft.exclude) { $rule in
                HStack(spacing: 6) {
                    TextField("pattern", text: $rule.pattern)
                    Toggle("regex", isOn: $rule.isRegex).toggleStyle(.checkbox)
                    Button(role: .destructive) {
                        draft.wrappedValue.exclude.removeAll { $0.id == rule.id }
                    } label: { Image(systemName: "minus.circle") }.buttonStyle(.borderless)
                }
            }
            Button("Add exclude") { draft.wrappedValue.exclude.append(SpiderExclude(pattern: "")) }
                .buttonStyle(.borderless)
        }
    }
}
