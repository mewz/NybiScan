"""Bench send engine: verbatim bytes, Content-Length toggle, host independence,
TLS no-verify, genuine failure."""

from __future__ import annotations

import socket
import threading
import time

from nybiscan.core.bench import engine

from ._proxyhelpers import RawCaptureOrigin, StallOrigin


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_verbatim_bytes_and_cl_off():
    origin = RawCaptureOrigin()
    raw = (
        b"FOOBAR /x?a=1 HTTP/1.1\r\nHost: whatever.test\r\n"
        b"X-Dup: a\r\nX-Dup: b\r\nWeIrD-CaSe: 1\r\nContent-Length: 999\r\n\r\nbody7!!"
    )
    resp = engine.send_raw("127.0.0.1", origin.port, False, raw, content_length_autofill=False)
    wire = origin.wait()
    # Exact bytes: unknown method, duplicate header, weird casing, and a
    # deliberately-wrong Content-Length all go out unchanged; nothing injected.
    assert wire == raw
    assert b"User-Agent" not in wire and b"Accept-Encoding" not in wire
    assert resp["status"] == 200 and resp["resp_body"] == b"ok"


def test_content_length_autofill_on_touches_only_cl():
    origin = RawCaptureOrigin()
    raw = b"POST /x HTTP/1.1\r\nHost: h\r\nContent-Length: 999\r\nX-Y: z\r\n\r\nhello"
    engine.send_raw("127.0.0.1", origin.port, False, raw, content_length_autofill=True)
    wire = origin.wait()
    assert b"Content-Length: 5" in wire  # matches body 'hello'
    assert b"999" not in wire
    assert b"X-Y: z" in wire  # nothing else touched


def test_connection_target_independent_of_host_header():
    origin = RawCaptureOrigin()
    # Connect to the origin (the bar) while the raw text carries a DIFFERENT Host.
    raw = b"GET / HTTP/1.1\r\nHost: totally-different.example:1234\r\n\r\n"
    resp = engine.send_raw("127.0.0.1", origin.port, False, raw, content_length_autofill=False)
    wire = origin.wait()
    # Socket went to the bar (we got a response) and the Host on the wire is the
    # one typed, not rewritten to the connection target.
    assert resp["status"] == 200
    assert b"Host: totally-different.example:1234" in wire


def test_tls_no_verify_self_signed_succeeds(tmp_path):
    origin = RawCaptureOrigin(tls=True, tmp=tmp_path)
    raw = b"GET / HTTP/1.1\r\nHost: self.test\r\n\r\n"
    resp = engine.send_raw("127.0.0.1", origin.port, True, raw, content_length_autofill=False)
    origin.wait()
    # A self-signed cert does NOT block the send (verification is off, like the proxy).
    assert resp["error"] is None
    assert resp["status"] == 200


def test_genuine_connection_failure_records_error():
    dead = _free_port()  # nothing listening
    resp = engine.send_raw("127.0.0.1", dead, False, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n",
                           content_length_autofill=False, timeout=2.0)
    assert resp["status"] is None
    assert resp["error"]  # a real connection failure is reported, not swallowed


def test_hanging_send_is_bounded_and_records_timeout():
    # A server that accepts but never responds (stand-in for a wrong Content-Length
    # the server waits to fill) must hit the timeout, not block unboundedly.
    origin = StallOrigin()
    try:
        start = time.time()
        resp = engine.send_raw("127.0.0.1", origin.port, False,
                               b"GET / HTTP/1.1\r\nHost: x\r\n\r\n",
                               content_length_autofill=False, timeout=0.5)
        elapsed = time.time() - start
        assert resp["status"] is None
        assert resp["error"] == "timeout"
        assert elapsed < 3.0  # bounded by the timeout, not an unbounded hang
    finally:
        origin.stop()


def test_inflight_send_can_be_cancelled():
    # A send against a nonresponsive server is aborted from another thread; it
    # records a 'cancelled' outcome (distinct from a timeout).
    origin = StallOrigin()
    token = engine.CancelToken()
    result = {}

    def run():
        result["resp"] = engine.send_raw(
            "127.0.0.1", origin.port, False, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n",
            content_length_autofill=False, timeout=10.0, cancel_token=token,
        )

    t = threading.Thread(target=run)
    t.start()
    assert origin.accepted.wait(3.0)  # the send has connected and is waiting
    time.sleep(0.1)
    token.cancel()
    t.join(3.0)
    try:
        assert not t.is_alive()  # cancel aborted promptly, well before the 10s timeout
        assert result["resp"]["status"] is None
        assert result["resp"]["error"] == "cancelled"
    finally:
        origin.stop()
