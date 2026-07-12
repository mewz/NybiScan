import Foundation

/// Pure navigation logic for a Bench tab's send history (Burp Repeater style
/// `<`/`>` stepping plus direct pick). `ids` are ordered oldest -> newest exactly
/// as the control API returns them; the newest send is the default view. Returns
/// `nil` when there is nothing to step to, so the caller can disable the arrow / no-op.
public enum BenchHistoryNav {
    /// The default entry to show (newest), or nil if the history is empty.
    public static func newest(_ ids: [Int]) -> Int? { ids.last }

    /// One step toward older sends from `current` (nil = newest).
    public static func older(_ ids: [Int], current: Int?) -> Int? {
        guard let cur = current ?? ids.last,
              let i = ids.firstIndex(of: cur), i > 0 else { return nil }
        return ids[i - 1]
    }

    /// One step toward newer sends from `current` (nil = newest).
    public static func newer(_ ids: [Int], current: Int?) -> Int? {
        guard let cur = current ?? ids.last,
              let i = ids.firstIndex(of: cur), i < ids.count - 1 else { return nil }
        return ids[i + 1]
    }
}
