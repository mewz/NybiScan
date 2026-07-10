"""The proxy listener and the control API are separate sockets on separate ports."""

from __future__ import annotations

import json
import socket
import threading
import urllib.request

from nybiscan.api.app import create_app
from nybiscan.api.server import pick_free_port
from nybiscan.api.state import AppState

from ._proxyhelpers import free_port, poll

TOKEN = "listener-token"


def _api(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_proxy_not_control_api(tmp_path):
    import uvicorn

    state = AppState(TOKEN)
    app = create_app(state)
    control_port = pick_free_port()
    base = f"http://127.0.0.1:{control_port}"

    config = uvicorn.Config(app, host="127.0.0.1", port=control_port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert poll(lambda: server.started, timeout=10)

        _api(base, "POST", "/projects", {"path": str(tmp_path / "l.nybiscan"), "name": "L"})

        proxy_port = free_port()
        status = _api(base, "POST", "/proxy/start", {"port": proxy_port})
        assert status["listen_port"] == proxy_port

        # Distinct ports.
        assert control_port != proxy_port

        # Both accept connections, on separate sockets.
        socket.create_connection(("127.0.0.1", control_port), timeout=5).close()
        socket.create_connection(("127.0.0.1", proxy_port), timeout=5).close()

        # The control API port speaks our JSON API (not the proxy protocol).
        health = json.loads(
            urllib.request.urlopen(f"{base}/health", timeout=5).read()
        )
        assert health["status"] == "ok"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
