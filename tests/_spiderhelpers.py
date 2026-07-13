"""Hermetic multi-page HTML origins for spider tests.

Records every requested path and the Cookie header seen, and serves per-path HTML so
a crawl walks a known link graph. No real network beyond loopback.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MapOrigin:
    """pages: dict path -> (content_type, body_str). Unlisted paths return 200 empty
    HTML so links are always followable. `links_html(base)` builds an anchor list."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []            # ordered list of requested paths (with query)
        self.cookies = {}              # path -> Cookie header value seen
        self.headers_seen = {}         # path -> dict of all request headers
        self._lock = threading.Lock()

        origin = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with origin._lock:
                    origin.requested.append(self.path)
                    origin.cookies[self.path] = self.headers.get("Cookie")
                    origin.headers_seen[self.path] = {k: v for k, v in self.headers.items()}
                path = self.path.split("?", 1)[0]
                ctype, body = origin.pages.get(path, ("text/html", "<html></html>"))
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()

    @property
    def paths(self):
        return [p.split("?", 1)[0] for p in self.requested]


def anchors(*hrefs) -> str:
    body = "".join(f'<a href="{h}">{h}</a>' for h in hrefs)
    return f"<html><body>{body}</body></html>"
