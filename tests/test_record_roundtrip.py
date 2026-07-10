"""Insert a request/response record, reopen, and read it back identically."""

from __future__ import annotations

from nybiscan.core import project as core_project
from nybiscan.core.schemas import CaptureStatus
from nybiscan.core.store import repository

from .conftest import make_record


def test_record_roundtrip(tmp_path):
    bundle = tmp_path / "rt.nybiscan"
    proj = core_project.create_project(bundle, name="RT")

    rec = make_record()
    proj.writer.enqueue(rec)
    proj.writer.flush()

    got = repository.get_entry(proj.read_conn, 1, ctx=proj.ctx)
    proj.close()

    assert got is not None
    assert got.host == "example.com"
    assert got.port == 443
    assert got.scheme == "https"
    assert got.method == "GET"
    assert got.url == "/api/v1/users?id=1"
    assert got.status == 200
    assert got.mime_type == "application/json"
    assert got.remote_ip == "93.184.216.34"
    assert got.req_headers_raw == rec.req_headers_raw
    assert got.resp_headers_raw == rec.resp_headers_raw
    assert got.resp_body == rec.resp_body
    assert got.resp_length == len(rec.resp_body)
    assert got.req_start_ts == rec.req_start_ts
    assert got.resp_complete_ts == rec.resp_complete_ts
    assert got.capture_status == CaptureStatus.complete


def test_pending_response(tmp_path):
    bundle = tmp_path / "pending.nybiscan"
    proj = core_project.create_project(bundle, name="P")

    rec = make_record(
        status=None,
        resp_body=None,
        mime_type=None,
        resp_complete_ts=None,
        capture_status=CaptureStatus.pending,
    )
    proj.writer.enqueue(rec)
    proj.writer.flush()

    got = repository.get_entry(proj.read_conn, 1, ctx=proj.ctx)
    proj.close()

    assert got.capture_status == CaptureStatus.pending
    assert got.status is None
    assert got.resp_body is None
