"""WAL is enabled on both the plaintext and the SQLCipher databases."""

from __future__ import annotations

from nybiscan.core import project as core_project


def _journal_mode(conn) -> str:
    return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()


def test_wal_plaintext(tmp_path):
    proj = core_project.create_project(tmp_path / "wal.nybiscan", name="W")
    assert _journal_mode(proj.read_conn) == "wal"
    proj.close()


def test_wal_encrypted(tmp_path):
    proj = core_project.create_project(
        tmp_path / "walenc.nybiscan", name="WE", passphrase="correct horse"
    )
    assert _journal_mode(proj.read_conn) == "wal"
    proj.close()
