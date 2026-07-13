import SwiftUI
import NybiScanKit

extension SitemapNode {
    // OutlineGroup needs an optional children key path (nil = leaf).
    var childrenOrNil: [SitemapNode]? { children.isEmpty ? nil : children }
}

/// Dashboard: passive site-map (over captured history) + scope management + the
/// live spider status. Thin client: all crawling/scope logic is in the core.
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
        .toolbar { sectionPicker }
        .task { await model.loadSitemap(); await model.loadScope() }
        .sheet(isPresented: sheetBinding) { SpiderStartSheet() }
        .alert("Spider", isPresented: Binding(
            get: { model.spiderError != nil }, set: { if !$0 { model.spiderError = nil } })
        ) {
            Button("OK", role: .cancel) { model.spiderError = nil }
        } message: { Text(model.spiderError ?? "") }
    }

    private var sectionPicker: some ToolbarContent {
        ToolbarItem(placement: .principal) {
            Picker("", selection: $model.section) {
                Text("History").tag(AppSection.history)
                Text("Bench").tag(AppSection.bench)
                Text("Dashboard").tag(AppSection.dashboard)
            }
            .pickerStyle(.segmented).frame(width: 280)
        }
    }

    private var sheetBinding: Binding<Bool> {
        Binding(get: { model.spiderDraft != nil }, set: { if !$0 { model.spiderDraft = nil } })
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

    // ----- site-map tree -----

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
                    ForEach(model.sitemap) { host in
                        Section("\(host.scheme)://\(host.host):\(host.port)") {
                            OutlineGroup(host.root.children, children: \.childrenOrNil) { node in
                                nodeRow(node)
                            }
                        }
                    }
                }
            }
        }
    }

    private func nodeRow(_ node: SitemapNode) -> some View {
        HStack(spacing: 6) {
            Image(systemName: node.entryIds.isEmpty ? "folder" : "doc.text")
                .font(.caption2).foregroundStyle(.secondary)
            Text(node.name).lineLimit(1)
            if node.sources.contains("spider") {
                Text("spider").font(.caption2).foregroundStyle(.orange)
            }
            Spacer()
            if !node.entryIds.isEmpty {
                Text("\(node.entryIds.count)").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if let id = node.entryIds.first { Task { await model.select(id: id) } }
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
/// requires explicit approval; the seed host and stored-session source are shown.
private struct SpiderStartSheet: View {
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
