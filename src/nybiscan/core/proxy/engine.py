"""In-process mitmproxy engine.

Runs a DumpMaster on a dedicated daemon thread with its own asyncio loop. Chosen
(over a subprocess) because the single-writer reuse constraint requires the addon
to share the in-process BatchWriter. start() blocks until the listener is bound
(the addon's running hook fires); stop() shuts the master down thread-safely.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Optional

ALLOW_INSECURE_ENV = "NYBISCAN_ALLOW_INSECURE"


def insecure_allowed() -> bool:
    """ssl_insecure (unverified upstream TLS) is honored ONLY under this guard."""
    return os.environ.get(ALLOW_INSECURE_ENV, "").strip().lower() in {"1", "true", "yes"}


class ProxyEngine:
    def __init__(
        self,
        project,
        listen_host: str,
        listen_port: int,
        confdir: Path,
        ssl_insecure: bool = False,
    ) -> None:
        if project is None:
            raise ValueError("ProxyEngine requires an open project to write into")
        self._project = project
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.confdir = Path(confdir)
        # ssl_insecure defaults False and is honored only under the env guard.
        self.ssl_insecure = bool(ssl_insecure and insecure_allowed())

        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._master = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 15.0) -> None:
        self._thread = threading.Thread(target=self._run, name="nybiscan-proxy", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            if self._error is not None:
                raise RuntimeError(f"proxy failed to start: {self._error}") from self._error
            raise RuntimeError("proxy failed to start within timeout")
        if self._error is not None:
            raise RuntimeError(f"proxy failed to start: {self._error}") from self._error

    def _run(self) -> None:
        from mitmproxy.options import Options
        from mitmproxy.tools.dump import DumpMaster

        from .addon import CaptureAddon

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            opts = Options(
                listen_host=self.listen_host,
                listen_port=self.listen_port,
                confdir=str(self.confdir),
                ssl_insecure=self.ssl_insecure,
            )
            self._master = DumpMaster(opts, loop=loop, with_termlog=False, with_dumper=False)
            self._master.addons.add(CaptureAddon(self._project, ready=self._ready))
            loop.run_until_complete(self._master.run())
        except BaseException as exc:  # noqa: BLE001 - surface startup errors to start()
            self._error = exc
            self._ready.set()  # unblock start() so it can raise
        finally:
            if self._loop is not None:
                self._loop.close()

    def stop(self, timeout: float = 15.0) -> None:
        if self._master is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._master.shutdown)
        if self._thread is not None:
            self._thread.join(timeout)

    def status(self) -> dict:
        return {
            "running": self.running,
            "listen_host": self.listen_host,
            "listen_port": self.listen_port,
            "ca_dir": str(self.confdir),
            "ssl_insecure": self.ssl_insecure,
        }
