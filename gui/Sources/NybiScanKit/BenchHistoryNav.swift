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

    /// The 1-based per-tab ordinal of the send at `index` in the oldest -> newest
    /// history array. This is the tab's own send sequence (1..N), NOT the global
    /// bench_history id, and matches the `x/N` position indicator.
    public static func ordinal(index: Int) -> Int { index + 1 }

    /// Indices (into the oldest -> newest history array) of the sends the dropdown
    /// should show: the most recent `cap` sends, ordered newest-first for display.
    /// A DISPLAY cap only - storage is unbounded and the `<`/`>` arrows still
    /// traverse the entire history, so ordinal 1 (the first send) stays reachable
    /// even when it falls outside this window.
    public static func windowIndices(count: Int, cap: Int = 25) -> [Int] {
        guard count > 0 else { return [] }
        let start = max(0, count - cap)  // most recent `cap` (or all if fewer)
        return Array((start..<count).reversed())  // newest-first
    }
}
