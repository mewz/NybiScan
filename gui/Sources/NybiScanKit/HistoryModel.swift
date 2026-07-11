import Foundation

/// Pure, testable history state. Rows are keyed by id (both backfill rows and WS
/// events carry the row id). entry_created inserts a pending placeholder;
/// entry_updated (and detail refetches) upsert the full row. No SwiftUI here so
/// the apply logic is unit-tested directly.
public struct HistoryModel: Equatable, Sendable {
    public private(set) var entries: [HistorySummary]
    private var indexById: [Int: Int]

    public init(_ backfill: [HistorySummary] = []) {
        self.entries = []
        self.indexById = [:]
        applyBackfill(backfill)
    }

    public mutating func applyBackfill(_ items: [HistorySummary]) {
        for item in items { upsert(item) }
    }

    /// Insert a pending placeholder from an entry_created event, unless the row
    /// already exists (a backfill or a faster update may have arrived first).
    public mutating func insertPending(from event: HistoryEvent) {
        if indexById[event.id] != nil { return }
        upsert(HistorySummary.pending(from: event))
    }

    /// Insert or replace a full row (from a detail refetch after entry_updated,
    /// or from backfill). Preserves ascending-by-id order.
    public mutating func upsert(_ summary: HistorySummary) {
        if let idx = indexById[summary.id] {
            entries[idx] = summary
            return
        }
        // Insert keeping entries sorted by id ascending.
        var insertAt = entries.count
        for (i, e) in entries.enumerated() where e.id > summary.id {
            insertAt = i
            break
        }
        entries.insert(summary, at: insertAt)
        rebuildIndex()
    }

    private mutating func rebuildIndex() {
        indexById.removeAll(keepingCapacity: true)
        for (i, e) in entries.enumerated() { indexById[e.id] = i }
    }

    public func entry(id: Int) -> HistorySummary? {
        indexById[id].map { entries[$0] }
    }
}
