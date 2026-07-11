"""Hermetic local origins + proxy client helpers for Plan 2 tests.

No network. A single handler serves a few behaviors by path; origins run over
http or https (self-signed). Requests are routed through the NybiScan proxy.
"""

from __future__ import annotations

import datetime
import gzip
import socket
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Handler(BaseHTTPRequestHandler):
    def _send(self, status, ctype, body, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/json":
            self._send(200, "application/json", b'{"ok":true,"cat":"nybble"}')
        elif path == "/image":
            self._send(200, "image/png", PNG_MAGIC + b"\x00" * 2048)
        elif path == "/gzip":
            raw = b"gzipped-plaintext-payload " * 20
            self._send(200, "text/plain", gzip.compress(raw), {"Content-Encoding": "gzip"})
        elif path == "/slow":
            time.sleep(0.8)
            self._send(200, "text/plain", b"slow-done")
        else:
            self._send(200, "text/html", b"<html>hello-nybble</html>")

    def log_message(self, *args):
        pass


def selfsigned_cert(tmp: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    certf = tmp / "origin.crt"
    keyf = tmp / "origin.key"
    certf.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyf.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return certf, keyf


class Origin:
    def __init__(self, https: bool = False, tmp: Path | None = None):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.scheme = "https" if https else "http"
        if https:
            assert tmp is not None
            certf, keyf = selfsigned_cert(tmp)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certf, keyf)
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path: str) -> str:
        return f"{self.scheme}://localhost:{self.port}{path}"

    def stop(self):
        self.server.shutdown()


def proxy_opener(proxy_port: int, ca_cert: Path | None = None):
    handlers = [urllib.request.ProxyHandler({
        "http": f"http://127.0.0.1:{proxy_port}",
        "https": f"http://127.0.0.1:{proxy_port}",
    })]
    if ca_cert is not None:
        ctx = ssl.create_default_context(cafile=str(ca_cert))
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def poll(predicate, timeout: float = 5.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()
