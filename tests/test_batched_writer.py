"""The writer batches: N>1 queued records commit in exactly one transaction."""

from __future__ import annotations

from nybiscan.core import project as core_project
from nybiscan.core.store import repository

from .conftest import make_record


def test_many_records_one_commit(tmp_path):
    proj = core_project.create_project(tmp_path / "batch.nybiscan", name="B")

    # Large flush_interval so ONLY the explicit flush() triggers a commit,
    # making the batching deterministic (no timer-driven partial flush).
    proj.writer._flush_interval = 60.0

    n = 50
    for i in range(n):
        proj.writer.enqueue(make_record(url=f"/item/{i}"))
    proj.writer.flush()

    # All records landed, and they did so in a single COMMIT.
    assert repository.count_history(proj.read_conn) == n
    assert proj.writer.commit_count == 1
    assert proj.writer.records_written == n

    proj.close()


def test_second_flush_is_second_commit(tmp_path):
    proj = core_project.create_project(tmp_path / "batch2.nybiscan", name="B2")
    proj.writer._flush_interval = 60.0

    for i in range(5):
        proj.writer.enqueue(make_record(url=f"/a/{i}"))
    proj.writer.flush()
    for i in range(5):
        proj.writer.enqueue(make_record(url=f"/b/{i}"))
    proj.writer.flush()

    assert proj.writer.commit_count == 2
    assert repository.count_history(proj.read_conn) == 10

    # An empty flush must NOT create a commit.
    proj.writer.flush()
    assert proj.writer.commit_count == 2

    proj.close()
