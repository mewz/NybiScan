"""Bench control API: tabs CRUD, send (records + returns), seeding, separation."""

from __future__ import annotations

import base64
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.core.schemas import HistoryRecord

from ._proxyhelpers import Origin, RawCaptureOrigin, StallOrigin

TOKEN = "bench-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        r = c.post("/projects", json={"path": str(tmp_path / "b.nybiscan"), "name": "B"}, headers=AUTH)
        assert r.status_code == 200
        yield c


def _seed_history(client, rec: HistoryRecord) -> int:
    state = client.app.state.app_state
    state.project.writer.enqueue(rec)
    state.project.writer.flush()
    return client.get("/history", headers=AUTH).json()[0]["id"]


def test_requires_auth(client):
    assert client.get("/bench/tabs").status_code == 401
    assert client.post("/bench/tabs", json={}).status_code == 401


def test_create_blank_tab_and_list(client):
    r = client.post("/bench/tabs", json={}, headers=AUTH)
    assert r.status_code == 200
    tab = r.json()
    assert tab["id"] and "HTTP/1.1" in tab["raw_request"]
    assert tab["content_length_autofill"] is True
    tabs = client.get("/bench/tabs", headers=AUTH).json()
    assert [t["id"] for t in tabs] == [tab["id"]]


def test_update_tab(client):
    tab = client.post("/bench/tabs", json={}, headers=AUTH).json()
    r = client.patch(
        f"/bench/tabs/{tab['id']}",
        json={"name": "Login test", "raw_request": "GET /login HTTP/1.1\r\nHost: h\r\n\r\n",
              "conn_tls": False, "content_length_autofill": False},
        headers=AUTH,
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["name"] == "Login test"
    assert updated["raw_request"].startswith("GET /login")
    assert updated["conn_tls"] is False and updated["content_length_autofill"] is False


def test_send_records_and_is_separate_from_proxy_history(client):
    origin = RawCaptureOrigin()
    tab = client.post("/bench/tabs", json={}, headers=AUTH).json()
    client.patch(
        f"/bench/tabs/{tab['id']}",
        json={"conn_host": "127.0.0.1", "conn_port": origin.port, "conn_tls": False,
              "raw_request": "GET /x HTTP/1.1\r\nHost: bench.test\r\n\r\n"},
        headers=AUTH,
    )
    r = client.post(f"/bench/tabs/{tab['id']}/send", headers=AUTH)
    assert r.status_code == 200
    send = r.json()
    assert send["status"] == 200
    assert base64.b64decode(send["resp_body_b64"]) == b"ok"

    # The send is in the tab's own history...
    hist = client.get(f"/bench/tabs/{tab['id']}/history", headers=AUTH).json()
    assert len(hist) == 1
    full = client.get(f"/bench/history/{hist[0]['id']}", headers=AUTH).json()
    assert full["req_raw"].startswith("GET /x")
    # ...and NOT in the main proxy history (separation).
    assert client.get("/history", headers=AUTH).json() == []


def test_seed_from_history_h1(client):
    rec = HistoryRecord(
        scheme="https", host="ex.com", port=443, method="POST", url="/login?x=1",
        req_headers_raw="POST /login?x=1 HTTP/1.1\r\nHost: ex.com\r\nContent-Type: application/json\r\n\r\n",
        req_body=b'{"u":"admin"}',
    )
    hid = _seed_history(client, rec)
    tab = client.post("/bench/tabs", json={"seed_history_id": hid}, headers=AUTH).json()
    assert tab["conn_host"] == "ex.com" and tab["conn_tls"] is True
    assert tab["raw_request"].startswith("POST /login?x=1 HTTP/1.1\r\nHost: ex.com")
    assert '{"u":"admin"}' in tab["raw_request"]


def test_seed_from_h2_reconstructs(client):
    # h2 capture: version HTTP/2.0, NO Host header.
    rec = HistoryRecord(
        scheme="https", host="ex.com", port=443, method="GET", url="/a",
        req_headers_raw="GET /a HTTP/2.0\r\naccept: */*\r\n\r\n", req_body=None,
    )
    hid = _seed_history(client, rec)
    tab = client.post("/bench/tabs", json={"seed_history_id": hid}, headers=AUTH).json()
    assert "GET /a HTTP/1.1" in tab["raw_request"]  # version normalized
    assert "Host: ex.com" in tab["raw_request"]  # Host injected


def test_seed_dropped_body_noted(client):
    # A binary request body is dropped by the capture filter on store, so the
    # reloaded record has req_body_dropped=True and cannot be replayed.
    rec = HistoryRecord(
        scheme="https", host="ex.com", port=443, method="POST", url="/upload",
        req_headers_raw="POST /upload HTTP/1.1\r\nHost: ex.com\r\n\r\n",
        req_mime_type="image/png", req_body=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
    )
    hid = _seed_history(client, rec)
    tab = client.post("/bench/tabs", json={"seed_history_id": hid}, headers=AUTH).json()
    assert "dropped_note" in tab and "dropped" in tab["dropped_note"].lower()


def test_delete_tab(client):
    tab = client.post("/bench/tabs", json={}, headers=AUTH).json()
    assert client.delete(f"/bench/tabs/{tab['id']}", headers=AUTH).json() == {"deleted": True}
    assert client.get("/bench/tabs", headers=AUTH).json() == []


@pytest.mark.parametrize("passphrase", [None, "close-secret-pass"])
def test_delete_tab_removes_its_history(tmp_path, passphrase):
    # Closing a Bench tab must leave NO orphaned bench_history rows (nothing kept
    # after close). Verified on plaintext AND encrypted bundles, since FK enforcement
    # / cascade behavior differs and the delete must not depend on it.
    c = TestClient(create_app(AppState(TOKEN)))
    with c:
        body = {"path": str(tmp_path / "d.nybiscan"), "name": "D"}
        if passphrase:
            body["passphrase"] = passphrase
        assert c.post("/projects", json=body, headers=AUTH).status_code == 200

        origin = Origin()
        tab = c.post("/bench/tabs", json={}, headers=AUTH).json()
        c.patch(
            f"/bench/tabs/{tab['id']}",
            json={"conn_host": "127.0.0.1", "conn_port": origin.port, "conn_tls": False,
                  "raw_request": "GET /json HTTP/1.1\r\nHost: h\r\n\r\n"},
            headers=AUTH,
        )
        for _ in range(3):
            assert c.post(f"/bench/tabs/{tab['id']}/send", headers=AUTH).json()["status"] == 200
        origin.stop()
        assert len(c.get(f"/bench/tabs/{tab['id']}/history", headers=AUTH).json()) == 3

        assert c.delete(f"/bench/tabs/{tab['id']}", headers=AUTH).json() == {"deleted": True}

        # Tab gone AND no history rows orphaned (asserted directly against the table).
        assert c.get("/bench/tabs", headers=AUTH).json() == []
        conn = c.app.state.app_state.project.read_conn
        remaining = conn.execute(
            "SELECT COUNT(*) FROM bench_history WHERE tab_id = ?", (tab["id"],)
        ).fetchone()[0]
        assert remaining == 0


def test_history_appends_in_order_and_persists_across_reopen(client, tmp_path):
    origin = Origin()  # multi-shot: serves each of several sends
    tab = client.post("/bench/tabs", json={}, headers=AUTH).json()
    client.patch(
        f"/bench/tabs/{tab['id']}",
        json={"conn_host": "127.0.0.1", "conn_port": origin.port, "conn_tls": False,
              "raw_request": "GET /json HTTP/1.1\r\nHost: h\r\n\r\n"},
        headers=AUTH,
    )
    for _ in range(3):
        assert client.post(f"/bench/tabs/{tab['id']}/send", headers=AUTH).json()["status"] == 200
    origin.stop()

    hist = client.get(f"/bench/tabs/{tab['id']}/history", headers=AUTH).json()
    assert len(hist) == 3  # append-only: every send kept, none overwritten
    ids = [h["id"] for h in hist]
    assert ids == sorted(ids) and len(set(ids)) == 3  # ascending append order, distinct
    for h in hist:
        full = client.get(f"/bench/history/{h['id']}", headers=AUTH).json()
        assert full["req_raw"].startswith("GET /json")  # request-as-sent round-trips
        assert full["status"] == 200

    # Close and reopen the SAME bundle: the tab's full send history survives.
    assert client.post("/projects/close", headers=AUTH).status_code == 200
    r = client.post("/projects/open", json={"path": str(tmp_path / "b.nybiscan")}, headers=AUTH)
    assert r.status_code == 200
    hist2 = client.get(f"/bench/tabs/{tab['id']}/history", headers=AUTH).json()
    assert [h["id"] for h in hist2] == ids


def test_cancel_no_inflight_is_noop(client):
    tab = client.post("/bench/tabs", json={}, headers=AUTH).json()
    r = client.post(f"/bench/tabs/{tab['id']}/cancel", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"cancelled": False}


def test_inflight_send_cancelled_records_outcome(client):
    # A send against a nonresponsive server, aborted by a concurrent /cancel, records
    # a 'cancelled' outcome in history (the core registry wiring end to end).
    origin = StallOrigin()
    tab = client.post("/bench/tabs", json={}, headers=AUTH).json()
    client.patch(
        f"/bench/tabs/{tab['id']}",
        json={"conn_host": "127.0.0.1", "conn_port": origin.port, "conn_tls": False,
              "raw_request": "GET / HTTP/1.1\r\nHost: h\r\n\r\n"},
        headers=AUTH,
    )
    result = {}

    def do_send():
        result["resp"] = client.post(f"/bench/tabs/{tab['id']}/send", headers=AUTH).json()

    t = threading.Thread(target=do_send)
    t.start()
    assert origin.accepted.wait(3.0)  # the send has connected and is waiting
    time.sleep(0.1)
    assert client.post(f"/bench/tabs/{tab['id']}/cancel", headers=AUTH).json() == {"cancelled": True}
    t.join(3.0)
    origin.stop()
    assert not t.is_alive()
    assert result["resp"]["status"] is None and result["resp"]["error"] == "cancelled"
