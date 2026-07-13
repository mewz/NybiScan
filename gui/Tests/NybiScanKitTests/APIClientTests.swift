import XCTest
@testable import NybiScanKit

final class APIClientTests: XCTestCase {
    override func tearDown() {
        StubURLProtocol.reset()
        super.tearDown()
    }

    func makeClient() -> ControlAPIClient {
        ControlAPIClient(port: 9999, token: "tok", session: StubURLProtocol.session())
    }

    // ----- request building (no network) -----

    func testRequestAttachesBearerTokenAndPath() {
        let client = ControlAPIClient(port: 4321, token: "sekret")
        let req = client.makeRequest("GET", "/proxy/status")
        XCTAssertEqual(req.httpMethod, "GET")
        XCTAssertEqual(req.url?.absoluteString, "http://127.0.0.1:4321/proxy/status")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer sekret")
    }

    func testPostRequestCarriesJSONBody() {
        let client = ControlAPIClient(port: 1, token: "t")
        let body = try! NybiCoders.makeEncoder().encode(ProxyStartPayload(ip: "127.0.0.1", port: 8080))
        let req = client.makeRequest("POST", "/proxy/start", body: body)
        XCTAssertEqual(req.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let json = String(data: req.httpBody!, encoding: .utf8)!
        XCTAssertTrue(json.contains("\"ssl_insecure\""))  // snake_case on the wire
    }

    // ----- decoding via the stub -----

    func testDecodesHistoryList() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data("""
            [{"id":1,"flow_id":"f1","scheme":"https","host":"ex.com","port":443,
              "method":"GET","url":"/a","status":200,"mime_type":"application/json",
              "resp_length":12,"remote_ip":"1.2.3.4","capture_status":"complete",
              "req_start_ts":1000,"resp_complete_ts":1100}]
            """.utf8))
        }
        let rows = try await makeClient().history()
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].flowId, "f1")
        XCTAssertEqual(rows[0].mimeType, "application/json")
        XCTAssertEqual(rows[0].captureStatus, "complete")
    }

    func testDecodesExtensionAndDerivesHasParams() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data("""
            [{"id":1,"flow_id":"f1","scheme":"https","host":"ex.com","port":443,
              "method":"GET","url":"/app.min.js?v=3","extension":"js","status":200,
              "mime_type":"application/javascript","resp_length":9,"remote_ip":"1.2.3.4",
              "capture_status":"complete","req_start_ts":1000,"resp_complete_ts":1100},
             {"id":2,"flow_id":"f2","scheme":"https","host":"ex.com","port":443,
              "method":"GET","url":"/api/users","extension":null,"status":200,
              "mime_type":"application/json","resp_length":2,"remote_ip":"1.2.3.4",
              "capture_status":"complete","req_start_ts":1000,"resp_complete_ts":1100}]
            """.utf8))
        }
        let rows = try await makeClient().history()
        // Assert the VALUE (a mismatched key would silently decode nil).
        XCTAssertEqual(rows[0].extension, "js")
        XCTAssertNil(rows[1].extension)
        // has_params is a client-side derivation, not from the payload.
        XCTAssertTrue(rows[0].hasParams)   // /app.min.js?v=3
        XCTAssertFalse(rows[1].hasParams)  // /api/users
        // statusSort makes the Optional status sortable.
        XCTAssertEqual(rows[0].statusSort, 200)
    }

    func testDecodesHistoryDetail() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data("""
            {"id":5,"flow_id":"f5","scheme":"http","host":"h","port":80,"method":"POST",
             "url":"/x","status":201,"mime_type":"text/html","resp_length":3,"remote_ip":null,
             "capture_status":"complete","req_start_ts":1,"resp_complete_ts":2,
             "req_headers_raw":"POST /x HTTP/1.1","req_mime_type":null,"req_body_b64":null,
             "req_body_dropped":false,"req_content_encoding":null,
             "resp_headers_raw":"HTTP/1.1 201","resp_body_b64":"YWJj","resp_body_dropped":false,
             "resp_content_encoding":"gzip"}
            """.utf8))
        }
        let detail = try await makeClient().historyEntry(id: 5)
        XCTAssertEqual(detail.id, 5)
        XCTAssertEqual(detail.respBodyB64, "YWJj")
        XCTAssertEqual(detail.respContentEncoding, "gzip")
        XCTAssertEqual(detail.summary.status, 201)
    }

    func testDecodesProxyStatusConfigAndCaInfo() async throws {
        StubURLProtocol.responder = { req in
            switch req.url!.path {
            case "/proxy/status":
                return (200, Data(#"{"running":true,"listen_host":"127.0.0.1","listen_port":8080,"ca_dir":"/x","ssl_insecure":false}"#.utf8))
            case "/config":
                return (200, Data(#"{"authorized_use_ack":false,"auto_start_proxy":true,"default_listen_ip":"127.0.0.1","default_listen_port":8080}"#.utf8))
            case "/ca/info":
                return (200, Data(#"{"scope":"global","exists":true,"confdir":"/g","cn":"mitmproxy","fingerprint_sha256":"ab","not_after":"2030"}"#.utf8))
            default:
                return (404, Data())
            }
        }
        let client = makeClient()
        let status = try await client.proxyStatus()
        XCTAssertTrue(status.running)
        XCTAssertEqual(status.sslInsecure, false)
        let cfg = try await client.getConfig()
        XCTAssertEqual(cfg.authorizedUseAck, false)
        XCTAssertEqual(cfg.autoStartProxy, true)  // decodes the value
        XCTAssertEqual(cfg.defaultListenPort, 8080)
        let ca = try await client.caInfo()
        XCTAssertEqual(ca.scope, "global")
        XCTAssertEqual(ca.cn, "mitmproxy")
    }

    func testUpdateConfigHitsPostConfig() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data(#"{"authorized_use_ack":false,"auto_start_proxy":false,"default_listen_ip":"127.0.0.1","default_listen_port":8080}"#.utf8))
        }
        let cfg = try await makeClient().updateConfig(autoStartProxy: false)
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/config")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertFalse(cfg.autoStartProxy)
    }

    func testExportCAHitsPostAndDecodes() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data(#"{"format":"pem","suggested_filename":"nybiscan-ca.crt","cert_b64":"YWJj"}"#.utf8))
        }
        let export = try await makeClient().exportCA(format: "pem")
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/ca/export")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(export.suggestedFilename, "nybiscan-ca.crt")
        XCTAssertEqual(export.certData, Data("abc".utf8))  // YWJj -> abc
    }

    func testBenchTabDecodesAndSeedNote() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data("""
            {"id":3,"name":"Login","order_index":1,"raw_request":"GET / HTTP/1.1\\r\\nHost: h\\r\\n\\r\\n",
             "conn_host":"h","conn_port":8443,"conn_tls":false,"content_length_autofill":true,
             "dropped_note":"body dropped"}
            """.utf8))
        }
        let tab = try await makeClient().createBenchTab(CreateBenchTabPayload(seedHistoryId: 9))
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/bench/tabs")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(tab.id, 3)
        XCTAssertEqual(tab.orderIndex, 1)
        XCTAssertEqual(tab.connPort, 8443)
        XCTAssertFalse(tab.connTls)
        XCTAssertTrue(tab.contentLengthAutofill)
        XCTAssertEqual(tab.droppedNote, "body dropped")
    }

    func testBenchUpdateHitsPatch() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data(#"{"id":1,"name":"n","order_index":0,"raw_request":"r","conn_host":"h","conn_port":443,"conn_tls":true,"content_length_autofill":false,"dropped_note":null}"#.utf8))
        }
        let tab = try await makeClient().updateBenchTab(1, UpdateBenchTabPayload(rawRequest: "r", connTls: true))
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/bench/tabs/1")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "PATCH")
        XCTAssertNil(tab.droppedNote)
        XCTAssertFalse(tab.contentLengthAutofill)
    }

    func testBenchSendDecodesResponse() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data("""
            {"id":5,"tab_id":1,"status":200,"resp_length":2,"mime_type":"text/plain","error":null,
             "sent_ts":10,"duration_ms":7,"req_raw":"GET /x HTTP/1.1","conn_host":"h","conn_port":443,
             "conn_tls":true,"content_length_autofill":true,"resp_headers_raw":"HTTP/1.1 200 OK",
             "resp_body_b64":"b2s=","resp_content_encoding":null}
            """.utf8))
        }
        let send = try await makeClient().benchSend(1)
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/bench/tabs/1/send")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(send.status, 200)
        XCTAssertEqual(send.reqRaw, "GET /x HTTP/1.1")
        XCTAssertEqual(send.respBodyB64, "b2s=")  // -> "ok"
    }

    func testBenchCancelHitsCancelPost() async throws {
        StubURLProtocol.responder = { _ in (200, Data(#"{"cancelled":true}"#.utf8)) }
        try await makeClient().benchCancel(3)
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/bench/tabs/3/cancel")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
    }

    // ----- bench history navigation model -----

    func testBenchHistoryNavStepsAndPicks() {
        let ids = [1, 2, 3]  // oldest -> newest, as the API returns
        XCTAssertEqual(BenchHistoryNav.newest(ids), 3)
        // From newest (nil), step older walks back one at a time; newer at newest is nil.
        XCTAssertEqual(BenchHistoryNav.older(ids, current: nil), 2)
        XCTAssertNil(BenchHistoryNav.newer(ids, current: nil))
        XCTAssertEqual(BenchHistoryNav.older(ids, current: 2), 1)
        XCTAssertNil(BenchHistoryNav.older(ids, current: 1))  // at the oldest end
        XCTAssertEqual(BenchHistoryNav.newer(ids, current: 1), 2)
        XCTAssertEqual(BenchHistoryNav.newer(ids, current: 2), 3)
    }

    func testBenchHistoryNavEmptyAndSingle() {
        XCTAssertNil(BenchHistoryNav.newest([]))
        XCTAssertNil(BenchHistoryNav.older([], current: nil))
        XCTAssertNil(BenchHistoryNav.older([9], current: nil))
        XCTAssertNil(BenchHistoryNav.newer([9], current: nil))
        XCTAssertEqual(BenchHistoryNav.newest([9]), 9)
    }

    func testDropdownWindowCapsAt25NewestFirstWithPerTabOrdinals() {
        // 30 sends, sitting at the newest: dropdown shows the most recent 25,
        // newest-first; ordinal is the 1-based per-tab position (index+1), NOT the
        // global bench_history id.
        let idx = BenchHistoryNav.windowIndices(count: 30, current: 29)
        XCTAssertEqual(idx.count, 25)
        XCTAssertEqual(idx.first, 29)  // newest (ordinal 30)
        XCTAssertEqual(idx.last, 5)    // oldest still in window (ordinal 6)
        XCTAssertEqual(BenchHistoryNav.ordinal(index: idx.first!), 30)
        XCTAssertEqual(BenchHistoryNav.ordinal(index: idx.last!), 6)
        // Send #1 (index 0) is OUTSIDE the newest window but reachable via the arrows.
        XCTAssertFalse(idx.contains(0))
        XCTAssertEqual(BenchHistoryNav.older(Array(0..<30), current: 5), 4)  // step past the window
    }

    func testDropdownWindowSlidesToContainCurrentPosition() {
        // 26 sends, sitting at position 2 (index 1): the window must slide to the old
        // end so #1 (index 0) AND the current #2 are both visible.
        let atTwo = BenchHistoryNav.windowIndices(count: 26, current: 1)
        XCTAssertEqual(atTwo.count, 25)
        XCTAssertTrue(atTwo.contains(0))  // #1 visible
        XCTAssertTrue(atTwo.contains(1))  // current #2 visible
        XCTAssertEqual(atTwo.first, 24)   // newest-of-band (ordinal 25); band is 1..25
        XCTAssertEqual(atTwo.last, 0)     // ordinal 1 at the bottom

        // 26 sends at the newest (index 25): window is the most recent 25 (2..26).
        let atLatest = BenchHistoryNav.windowIndices(count: 26, current: 25)
        XCTAssertEqual(atLatest.count, 25)
        XCTAssertEqual(atLatest.first, 25)      // ordinal 26
        XCTAssertFalse(atLatest.contains(0))    // #1 not in the newest band
        XCTAssertEqual(atLatest.last, 1)        // ordinal 2

        // The arrow still reaches the true oldest regardless of the window: < from
        // position 2 (index 1) reaches position 1 (index 0).
        XCTAssertEqual(BenchHistoryNav.older(Array(0..<26), current: 1), 0)
    }

    func testDropdownWindowReflectsCurrentCount() {
        // Regression: the dropdown must reflect the tab's CURRENT send count, not a
        // stale earlier one (bug: counter showed 10/10 while the list stuck at 7).
        let atSeven = BenchHistoryNav.windowIndices(count: 7, current: 6)
        XCTAssertEqual(atSeven.count, 7)
        XCTAssertEqual(atSeven.first, 6)  // newest of 7 (ordinal 7)
        let atTen = BenchHistoryNav.windowIndices(count: 10, current: 9)
        XCTAssertEqual(atTen.count, 10)
        XCTAssertEqual(atTen.first, 9)  // newest of 10 (ordinal 10), not frozen at 7
        XCTAssertEqual(BenchHistoryNav.ordinal(index: atTen.first!), 10)
    }

    func testDropdownWindowShowsAllWhenFewerThan25() {
        // Two independent tabs each number their own sends from 1 (per-tab, not global).
        let idx = BenchHistoryNav.windowIndices(count: 3, current: 2)
        XCTAssertEqual(idx, [2, 1, 0])  // newest-first
        XCTAssertEqual(idx.map { BenchHistoryNav.ordinal(index: $0) }, [3, 2, 1])
        XCTAssertEqual(BenchHistoryNav.windowIndices(count: 0, current: 0), [])
    }

    // ----- Plan 5: scope, site-map, spider -----

    func testSitemapDecodesTree() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data("""
            [{"scheme":"https","host":"www.test","port":443,"entry_count":2,
              "root":{"name":"/","full_path":"/","entry_ids":[],"methods":[],"statuses":[],
                      "sources":[],"children":[
                {"name":"cgi","full_path":"/cgi","entry_ids":[],"methods":[],"statuses":[],
                 "sources":[],"children":[
                  {"name":"u.php","full_path":"/cgi/u.php","entry_ids":[7],"methods":["GET"],
                   "statuses":[200],"sources":["spider"],"children":[]}]}]}}]
            """.utf8))
        }
        let hosts = try await makeClient().sitemap()
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/sitemap")
        XCTAssertEqual(hosts.count, 1)
        let php = hosts[0].root.children[0].children[0]
        XCTAssertEqual(php.fullPath, "/cgi/u.php")
        XCTAssertEqual(php.entryIds, [7])
        XCTAssertEqual(php.sources, ["spider"])
    }

    func testScopeAddAndUpdatePaths() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data(#"[{"id":1,"host":"a.test","note":null,"headers":"Cookie: s=1\r\n"}]"#.utf8))
        }
        let after = try await makeClient().addScope(ScopeAddPayload(host: "a.test", headers: "Cookie: s=1\r\n"))
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/scope")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(after.first?.host, "a.test")
        XCTAssertEqual(after.first?.headers, "Cookie: s=1\r\n")

        _ = try await makeClient().updateScope("a.test", ScopeUpdatePayload(headers: "Cookie: s=2\r\n"))
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/scope/a.test")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "PUT")

        try await makeClient().removeScope("a.test")
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/scope/a.test")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "DELETE")
    }

    func testSpiderStartAndStatusDecode() async throws {
        StubURLProtocol.responder = { _ in
            (200, Data(#"{"running":true,"found":3,"saved":2,"cap":300,"current":"https://a/x","run_id":"r1"}"#.utf8))
        }
        let payload = SpiderStartPayload(
            seedHistoryId: 5, maxDepth: 2,
            exclude: [SpiderExclude(pattern: "/logout"), SpiderExclude(pattern: "/api/v\\d", isRegex: true)],
            rateLimitMs: 0
        )
        let st = try await makeClient().spiderStart(payload)
        XCTAssertEqual(StubURLProtocol.lastRequest?.url?.path, "/spider/start")
        XCTAssertEqual(StubURLProtocol.lastRequest?.httpMethod, "POST")
        XCTAssertEqual(st.found, 3)
        XCTAssertEqual(st.saved, 2)
        XCTAssertEqual(st.runId, "r1")

        // Exclude entries encode as pattern + is_regex only (id is a client-side key).
        let enc = NybiCoders.makeEncoder()
        let json = String(data: try enc.encode(SpiderExclude(pattern: "/x", isRegex: true)), encoding: .utf8)!
        XCTAssertTrue(json.contains("\"is_regex\":true"), json)
        XCTAssertFalse(json.contains("\"id\""), json)
    }

    func testSpiderStartOutOfScopeSurfacesError() async {
        StubURLProtocol.responder = { _ in
            (400, Data(#"{"detail":"seed host 'a.test' not in scope - add it first"}"#.utf8))
        }
        do {
            _ = try await makeClient().spiderStart(SpiderStartPayload(seedHistoryId: 1))
            XCTFail("expected error")
        } catch let err as ControlAPIError {
            XCTAssertEqual(err.status, 400)
            XCTAssertTrue(err.body.contains("not in scope"))
        } catch {
            XCTFail("wrong error type: \(error)")
        }
    }

    func testNon2xxThrowsControlAPIError() async {
        StubURLProtocol.responder = { _ in (401, Data(#"{"detail":"invalid token"}"#.utf8)) }
        do {
            _ = try await makeClient().getConfig()
            XCTFail("expected error")
        } catch let err as ControlAPIError {
            XCTAssertEqual(err.status, 401)
        } catch {
            XCTFail("wrong error type: \(error)")
        }
    }

    // ----- health poller -----

    func testHealthPollerTimesOutWhenCoreDown() async {
        StubURLProtocol.responder = { _ in (503, Data()) }
        let ok = await HealthPoller.waitForHealthy(client: makeClient(), timeoutSeconds: 0.3, intervalSeconds: 0.05)
        XCTAssertFalse(ok)
    }

    func testHealthPollerSucceedsWhenHealthy() async {
        StubURLProtocol.responder = { _ in (200, Data(#"{"status":"ok","version":"0.1.0","project_open":false}"#.utf8)) }
        let ok = await HealthPoller.waitForHealthy(client: makeClient(), timeoutSeconds: 1.0, intervalSeconds: 0.05)
        XCTAssertTrue(ok)
    }
}
