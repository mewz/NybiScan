"""Shared fixtures. Uses fast Argon2id params so encrypted-project tests are quick."""

from __future__ import annotations

import pytest

from nybiscan.core import crypto
from nybiscan.core.schemas import (
    CaptureStatus,
    HistoryRecord,
)


@pytest.fixture(autouse=True)
def isolate_ca_home(tmp_path, monkeypatch):
    """Point the global CA + app-support dir at per-test temp dirs so nothing
    touches ~/.nybiscan or the user's real config.toml / runtime.json."""
    monkeypatch.setenv("NYBISCAN_CA_DIR", str(tmp_path / "ca-global"))
    monkeypatch.setenv("NYBISCAN_SUPPORT_DIR", str(tmp_path / "support"))
    # Never allow insecure upstream TLS by default; tests that need it opt in.
    monkeypatch.delenv("NYBISCAN_ALLOW_INSECURE", raising=False)


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    """Shrink Argon2id cost for tests. Real defaults are used in production."""
    import secrets

    from nybiscan.core.schemas import KdfParams

    def _fast_params() -> KdfParams:
        return KdfParams(
            kdf="argon2id",
            argon2_version=19,
            m_cost=8,  # 8 KiB, test-only
            t_cost=1,
            parallelism=1,
            salt=secrets.token_bytes(16).hex(),
        )

    monkeypatch.setattr(crypto, "default_kdf_params", _fast_params)


def make_record(**overrides) -> HistoryRecord:
    base = dict(
        scheme="https",
        host="example.com",
        port=443,
        method="GET",
        url="/api/v1/users?id=1",
        req_headers_raw="GET /api/v1/users?id=1 HTTP/1.1\r\nHost: example.com\r\n\r\n",
        req_mime_type=None,
        req_body=None,
        req_start_ts=1_700_000_000_000,
        status=200,
        mime_type="application/json",
        remote_ip="93.184.216.34",
        resp_headers_raw="HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n",
        resp_body=b'{"users":[{"id":1,"name":"nybble"}]}',
        resp_complete_ts=1_700_000_000_120,
        capture_status=CaptureStatus.complete,
    )
    base.update(overrides)
    return HistoryRecord(**base)
