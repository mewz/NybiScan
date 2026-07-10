"""Binary/image bodies are dropped (metadata kept); text/json bodies are kept."""

from __future__ import annotations

from nybiscan.core import project as core_project
from nybiscan.core.store import repository

from .conftest import make_record


def test_binary_body_dropped_metadata_kept(tmp_path):
    proj = core_project.create_project(tmp_path / "bf.nybiscan", name="BF")

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096
    rec = make_record(mime_type="image/png", resp_body=png)
    proj.writer.enqueue(rec)
    proj.writer.flush()

    got = repository.get_entry(proj.read_conn, 1, ctx=proj.ctx)
    proj.close()

    # Body dropped, but mime and length retained.
    assert got.resp_body is None
    assert got.resp_body_dropped is True
    assert got.mime_type == "image/png"
    assert got.resp_length == len(png)


def test_text_body_kept(tmp_path):
    proj = core_project.create_project(tmp_path / "bf2.nybiscan", name="BF2")

    body = b'{"ok":true}'
    rec = make_record(mime_type="application/json", resp_body=body)
    proj.writer.enqueue(rec)
    proj.writer.flush()

    got = repository.get_entry(proj.read_conn, 1, ctx=proj.ctx)
    proj.close()

    assert got.resp_body == body
    assert got.resp_body_dropped is False


def test_large_text_body_spills_to_file(tmp_path):
    bundle = tmp_path / "spill.nybiscan"
    proj = core_project.create_project(bundle, name="Spill")
    # Shrink threshold so we do not need a megabyte in the test.
    proj.writer._ctx.spill_threshold = 1024
    proj.ctx.spill_threshold = 1024

    big = b"a" * 5000  # text/plain over threshold
    rec = make_record(mime_type="text/plain", resp_body=big)
    proj.writer.enqueue(rec)
    proj.writer.flush()

    got = repository.get_entry(proj.read_conn, 1, ctx=proj.ctx)
    # Spilled file exists and body is transparently reloaded on read.
    assert got.resp_body_ref is not None
    assert (bundle / "bodies" / got.resp_body_ref).exists()
    assert got.resp_body == big
    proj.close()
