import XCTest
@testable import NybiScanKit

final class RuntimeInfoTests: XCTestCase {
    func testParsesRuntimeJson() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("rt-\(UUID().uuidString).json")
        try Data(#"{"port":54321,"token":"abc","pid":42}"#.utf8).write(to: url)
        let info = try RuntimeInfoReader.read(from: url)
        XCTAssertEqual(info.port, 54321)
        XCTAssertEqual(info.token, "abc")
    }

    func testMissingFileThrowsMissing() {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("nope-\(UUID().uuidString).json")
        XCTAssertThrowsError(try RuntimeInfoReader.read(from: url)) { err in
            XCTAssertEqual(err as? RuntimeInfoError, .missing)
        }
    }

    func testMalformedFileThrowsMalformed() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bad-\(UUID().uuidString).json")
        try Data("not json".utf8).write(to: url)
        XCTAssertThrowsError(try RuntimeInfoReader.read(from: url)) { err in
            guard case .malformed = (err as? RuntimeInfoError) else {
                return XCTFail("expected .malformed")
            }
        }
    }

    func testReadsFreshEachTime() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("fresh-\(UUID().uuidString).json")
        try Data(#"{"port":1,"token":"a","pid":null}"#.utf8).write(to: url)
        XCTAssertEqual(try RuntimeInfoReader.read(from: url).port, 1)
        // Port changes on the next launch; a fresh read must see the new value.
        try Data(#"{"port":2,"token":"b","pid":null}"#.utf8).write(to: url)
        XCTAssertEqual(try RuntimeInfoReader.read(from: url).port, 2)
    }
}

final class WebSocketAuthTests: XCTestCase {
    func testAuthViaHeaderAndSubprotocolNotQuery() {
        let req = WebSocketAuth.makeRequest(port: 7777, token: "tok123")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer tok123")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Sec-WebSocket-Protocol"), "nybiscan, tok123")
        // The token must NOT appear in the URL.
        XCTAssertNil(req.url?.query)
        XCTAssertFalse(req.url!.absoluteString.contains("tok123"))
    }

    func testDecodesEvents() {
        let created = HistoryEventDecoder.decode(#"{"type":"entry_created","id":3,"flow_id":"f","host":"h","method":"GET","url":"/a","status":null,"capture_status":"pending"}"#)
        XCTAssertEqual(created?.type, "entry_created")
        XCTAssertEqual(created?.id, 3)
        XCTAssertEqual(created?.captureStatus, "pending")
        XCTAssertNil(HistoryEventDecoder.decode("garbage"))
    }
}

final class HistoryModelTests: XCTestCase {
    func event(_ type: String, id: Int, status: Int?, cap: String) -> HistoryEvent {
        HistoryEvent(type: type, id: id, flowId: "f\(id)", host: "h", method: "GET",
                     url: "/u\(id)", status: status, captureStatus: cap)
    }

    func testCreatedThenUpdatedFlipsRowToComplete() {
        var model = HistoryModel()
        // entry_created -> a pending placeholder row appears
        model.insertPending(from: event("entry_created", id: 1, status: nil, cap: "pending"))
        XCTAssertEqual(model.entries.count, 1)
        XCTAssertEqual(model.entry(id: 1)?.captureStatus, "pending")
        XCTAssertNil(model.entry(id: 1)?.status)

        // entry_updated -> the app refetches the full row and upserts it
        let full = HistorySummary(
            id: 1, flowId: "f1", scheme: "https", host: "h", port: 443, method: "GET",
            url: "/u1", status: 200, mimeType: "text/html", respLength: 10, remoteIp: "1.1.1.1",
            captureStatus: "complete", reqStartTs: 5, respCompleteTs: 6
        )
        model.upsert(full)
        XCTAssertEqual(model.entries.count, 1)  // still one row (replaced, not duplicated)
        XCTAssertEqual(model.entry(id: 1)?.captureStatus, "complete")
        XCTAssertEqual(model.entry(id: 1)?.status, 200)
        XCTAssertEqual(model.entry(id: 1)?.mimeType, "text/html")
    }

    func testBackfillThenLiveKeepsSortedUniqueRows() {
        var model = HistoryModel([
            HistorySummary(id: 1, flowId: "f1", scheme: "http", host: "h", port: 80, method: "GET",
                           url: "/1", status: 200, mimeType: nil, respLength: 0, remoteIp: nil,
                           captureStatus: "complete", reqStartTs: 1, respCompleteTs: 2),
        ])
        model.insertPending(from: event("entry_created", id: 2, status: nil, cap: "pending"))
        // a duplicate created for an existing id must not add a second row
        model.insertPending(from: event("entry_created", id: 1, status: nil, cap: "pending"))
        XCTAssertEqual(model.entries.map(\.id), [1, 2])
        XCTAssertEqual(model.entry(id: 1)?.captureStatus, "complete")  // unchanged by dup
    }
}

final class CoreProcessTests: XCTestCase {
    func testDefaultBinPathHonorsEnv() {
        setenv("NYBISCAN_BIN", "/custom/nybiscan", 1)
        defer { unsetenv("NYBISCAN_BIN") }
        XCTAssertEqual(CoreProcess.defaultBinPath(), "/custom/nybiscan")
    }

    func testStartThrowsWhenBinaryMissing() {
        let proc = CoreProcess(binPath: "/definitely/not/here/nybiscan")
        XCTAssertThrowsError(try proc.start()) { err in
            XCTAssertEqual(err as? CoreProcessError, .binaryNotFound("/definitely/not/here/nybiscan"))
        }
    }
}
