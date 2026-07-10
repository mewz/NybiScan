"""JSONL interchange export.

This is an EXPORT format, not the working store. The live session stays
relational (SQLite/SQLCipher). Bodies are base64-encoded so the dump is a single
portable text file. Decision recorded in DECISIONS.md: export is implemented as
JSONL now (not stubbed).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from .project import Project


def _b64(data) -> str | None:
    if data is None:
        return None
    return base64.b64encode(data).decode("ascii")


def export_jsonl(project: Project, out_path: Path | str) -> int:
    """Write every history record to out_path as JSONL. Returns record count."""
    out = Path(out_path).expanduser()
    from .store import repository

    records = repository.get_history(project.read_conn, limit=10_000_000, ctx=project.ctx)
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            data = rec.model_dump()
            data["req_body"] = _b64(rec.req_body)
            data["resp_body"] = _b64(rec.resp_body)
            data["capture_status"] = rec.capture_status.value
            f.write(json.dumps(data) + "\n")
    return len(records)
