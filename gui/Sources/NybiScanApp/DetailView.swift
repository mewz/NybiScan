import SwiftUI

struct DetailView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let d = model.detail {
            VStack(alignment: .leading, spacing: 8) {
                Text("\(d.method) \(d.scheme)://\(d.host):\(d.port)\(d.url)")
                    .font(.headline).textSelection(.enabled)
                    .padding([.top, .horizontal])
                RequestResponseView(detail: d, tab: $model.detailUI.tab)
            }
        } else {
            Text("Select a request")
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
