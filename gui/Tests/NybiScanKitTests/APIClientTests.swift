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
