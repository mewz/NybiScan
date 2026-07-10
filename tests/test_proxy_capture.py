"""End-to-end capture through the in-process proxy engine (http + https)."""

from __future__ import annotations

import threading

import pytest

from nybiscan.core import ca
from nybiscan.core import project as core_project
from nybiscan.core.proxy.engine import ProxyEngine
from nybiscan.core.store import repository

from ._proxyhelpers import Origin, free_port, poll, proxy_opener


@pytest.fixture
def make_capture(tmp_path):
    created = []

    def _make(https=False, ssl_insecure=False, passphrase=None):
        idx = len(created)
        proj = core_project.create_project(
            tmp_path / f"p{idx}.nybiscan", name="P", passphrase=passphrase
        )
        origin = Origin(https=https, tmp=tmp_path)
        confdir = ca.resolve_confdir(proj.bundle)
        ca_cert = ca.export_cert(confdir, tmp_path / f"ca{idx}.pem", "pem")
        port = free_port()
        eng = ProxyEngine(proj, "127.0.0.1", port, confdir, ssl_insecure=ssl_insecure)
        eng.start()
        opener = proxy_opener(port, ca_cert=ca_cert if https else None)
        created.append((eng, origin, proj))
        return {"proj": proj, "eng": eng, "origin": origin, "opener": opener, "port": port}

    yield _make

    for eng, origin, proj in reversed(created):
        for stop in (eng.stop, origin.stop, proj.close):
            try:
                stop()
            except Exception:
                pass


def _history(cap):
    return repository.get_history(cap["proj"].read_conn, ctx=cap["proj"].ctx)


def _find(cap, status=None, url=None):
    cap["proj"].writer.flush()
    for h in _history(cap):
        if status and h.capture_status.value != status:
            continue
        if url and h.url != url:
            continue
        return h
    return None


def test_http_capture(make_capture):
    cap = make_capture()
    r = cap["opener"].open(cap["origin"].url("/json?x=1"), timeout=10)
    assert r.status == 200

    rec = poll(lambda: _find(cap, "complete", "/json?x=1"))
    assert rec is not None
    assert rec.method == "GET"
    assert rec.host == "localhost"
    assert rec.port == cap["origin"].port
    assert rec.scheme == "http"
    assert rec.status == 200
    assert rec.mime_type == "application/json"
    assert rec.remote_ip in ("127.0.0.1", "::1")
    assert rec.req_start_ts > 0 and rec.resp_complete_ts > 0
    assert rec.resp_body == b'{"ok":true,"cat":"nybble"}'
    assert "Host:" in rec.req_headers_raw


def test_https_capture_via_ca(make_capture, monkeypatch):
    monkeypatch.setenv("NYBISCAN_ALLOW_INSECURE", "1")
    cap = make_capture(https=True, ssl_insecure=True)
    assert cap["eng"].ssl_insecure is True

    body = cap["opener"].open(cap["origin"].url("/"), timeout=10).read()
    assert b"hello-nybble" in body

    rec = poll(lambda: _find(cap, "complete"))
    assert rec is not None
    assert rec.scheme == "https"
    assert rec.status == 200
    assert b"hello-nybble" in rec.resp_body


def test_pending_then_complete(make_capture):
    cap = make_capture()

    def do_request():
        try:
            cap["opener"].open(cap["origin"].url("/slow"), timeout=10).read()
        except Exception:
            pass

    t = threading.Thread(target=do_request)
    t.start()
    # The /slow origin sleeps, so a pending row is observable first.
    pending = poll(lambda: _find(cap, "pending"), timeout=3)
    assert pending is not None
    assert pending.status is None

    t.join()
    complete = poll(lambda: _find(cap, "complete"), timeout=3)
    assert complete is not None
    assert complete.status == 200


def test_error_path(make_capture):
    cap = make_capture()
    dead = free_port()  # nothing is listening here
    try:
        cap["opener"].open(f"http://127.0.0.1:{dead}/x", timeout=10).read()
    except Exception:
        pass  # the proxy returns an error status to the client; we assert on capture
    rec = poll(lambda: _find(cap, "error"), timeout=5)
    assert rec is not None


def test_live_filter_text_only(make_capture):
    cap = make_capture()
    cap["opener"].open(cap["origin"].url("/image"), timeout=10).read()
    cap["opener"].open(cap["origin"].url("/json"), timeout=10).read()

    img = poll(lambda: _find(cap, "complete", "/image"))
    js = poll(lambda: _find(cap, "complete", "/json"))
    assert img is not None and js is not None

    # Binary body dropped, metadata kept.
    assert img.resp_body is None
    assert img.resp_body_dropped is True
    assert img.mime_type == "image/png"
    assert img.resp_length > 0
    # Text body kept.
    assert js.resp_body == b'{"ok":true,"cat":"nybble"}'
    assert js.resp_body_dropped is False


def test_auto_decompress(make_capture):
    cap = make_capture()
    cap["opener"].open(cap["origin"].url("/gzip"), timeout=10).read()
    rec = poll(lambda: _find(cap, "complete", "/gzip"))
    assert rec is not None
    assert rec.resp_content_encoding == "gzip"
    # Stored body is the DECOMPRESSED plaintext.
    assert b"gzipped-plaintext-payload" in rec.resp_body


def test_writer_reuse_single_writer(make_capture):
    cap = make_capture()
    proj = cap["proj"]

    calls = {"insert": 0, "update": 0}
    orig_insert = proj.writer.enqueue
    orig_update = proj.writer.enqueue_update_response

    def spy_insert(rec):
        calls["insert"] += 1
        return orig_insert(rec)

    def spy_update(flow_id, patch):
        calls["update"] += 1
        return orig_update(flow_id, patch)

    proj.writer.enqueue = spy_insert
    proj.writer.enqueue_update_response = spy_update

    # Burst concurrently so multiple ops land in a single flush (batching).
    n = 8
    threads = [
        threading.Thread(
            target=lambda i=i: cap["opener"].open(cap["origin"].url(f"/json?i={i}"), timeout=10).read()
        )
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    poll(lambda: len([h for h in _history(cap) if h.capture_status.value == "complete"]) >= n)

    # All captures went through the project's existing BatchWriter.
    assert calls["insert"] >= n
    assert calls["update"] >= n
    assert proj.writer.records_written >= n
    # Batched: far fewer commits than the ~2n ops enqueued.
    total_ops = calls["insert"] + calls["update"]
    assert proj.writer.commit_count < total_ops
    # Single db: history row count equals what the one writer wrote.
    assert len(_history(cap)) == proj.writer.records_written


def test_encrypted_capture_no_plaintext_bodies(make_capture):
    cap = make_capture(passphrase="correct horse")
    cap["opener"].open(cap["origin"].url("/json"), timeout=10).read()
    rec = poll(lambda: _find(cap, "complete", "/json"))
    assert rec is not None
    assert rec.resp_body == b'{"ok":true,"cat":"nybble"}'
    # Encrypted projects never spill bodies to disk.
    assert not (cap["proj"].bundle / "bodies").exists()


def test_ssl_insecure_defaults_off_without_env(make_capture):
    # No NYBISCAN_ALLOW_INSECURE in the environment (autouse fixture clears it).
    cap = make_capture(https=False, ssl_insecure=True)
    assert cap["eng"].ssl_insecure is False
    assert cap["eng"].status()["ssl_insecure"] is False
