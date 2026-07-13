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
    /// should show: a window of up to `cap` sends that always CONTAINS `current` and
    /// slides as the user navigates (like Burp), ordered newest-first for display.
    /// A DISPLAY cap only - storage is unbounded and the `<`/`>` arrows still traverse
    /// the entire history. Because the window follows the position, the current entry
    /// and its neighbours (e.g. ordinal 1 when sitting at ordinal 2) are always
    /// visible; at the newest end it shows the most recent `cap`.
    public static func windowIndices(count: Int, current: Int, cap: Int = 25) -> [Int] {
        guard count > 0 else { return [] }
        let size = min(cap, count)
        let cur = min(max(current, 0), count - 1)
        // Center the window on the current index, then clamp within bounds so it stays
        // a contiguous size-`cap` band that includes `current`.
        var start = cur - size / 2
        start = min(max(start, 0), count - size)
        return Array((start..<(start + size)).reversed())  // newest-first
    }
}
