import SwiftUI

struct DetailView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let d = model.detail {
            VStack(alignment: .leading, spacing: 8) {
                Text("\(d.method) \(d.scheme)://\(d.host):\(d.port)\(d.url)")
                    .font(.headline).textSelection(.enabled)
                    .padding([.top, .horizontal])
                RequestResponseView(
                    detail: d, tab: $model.detailUI.tab,
                    secondaryActions: [
                        MenuAction(title: "Send to Bench") { Task { await model.sendToBench(historyId: d.id) } },
                        MenuAction(title: "Add to Scope") { Task { await model.addToScope(historyId: d.id) } },
                        MenuAction(title: "Update Scope Session") { Task { await model.updateScopeSession(historyId: d.id) } },
                        MenuAction(title: "Spider from This") { Task { await model.prepareSpider(historyId: d.id) } },
                    ]
                )
            }
        } else {
            Text("Select a request")
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
