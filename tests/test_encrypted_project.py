"""Encrypted project: right passphrase opens, wrong fails, no plaintext bodies."""

from __future__ import annotations

import pytest

from nybiscan.core import project as core_project
from nybiscan.core.errors import PassphraseRequiredError, WrongPassphraseError
from nybiscan.core.store import repository

from .conftest import make_record

PASSPHRASE = "correct horse battery staple"


def test_reopen_correct_passphrase(tmp_path):
    bundle = tmp_path / "enc.nybiscan"
    proj = core_project.create_project(bundle, name="Enc", passphrase=PASSPHRASE)
    proj.writer.enqueue(make_record())
    proj.writer.flush()
    proj.close()

    reopened = core_project.open_project(bundle, passphrase=PASSPHRASE)
    assert repository.count_history(reopened.read_conn) == 1
    reopened.close()


def test_wrong_passphrase_fails(tmp_path):
    bundle = tmp_path / "enc2.nybiscan"
    core_project.create_project(bundle, name="Enc2", passphrase=PASSPHRASE).close()

    with pytest.raises(WrongPassphraseError):
        core_project.open_project(bundle, passphrase="wrong passphrase")


def test_missing_passphrase_fails(tmp_path):
    bundle = tmp_path / "enc3.nybiscan"
    core_project.create_project(bundle, name="Enc3", passphrase=PASSPHRASE).close()

    with pytest.raises(PassphraseRequiredError):
        core_project.open_project(bundle)


def test_no_plaintext_bodies_dir_for_encrypted(tmp_path):
    bundle = tmp_path / "enc4.nybiscan"
    proj = core_project.create_project(bundle, name="Enc4", passphrase=PASSPHRASE)

    # A large text body that WOULD spill in an unencrypted project stays in-db.
    proj.writer.enqueue(make_record(mime_type="text/plain", resp_body=b"x" * (1024 * 1024)))
    proj.writer.flush()
    proj.close()

    # Encrypted projects never create a bodies/ directory, so no plaintext leaks.
    assert not (bundle / "bodies").exists()

    reopened = core_project.open_project(bundle, passphrase=PASSPHRASE)
    got = repository.get_entry(reopened.read_conn, 1, ctx=reopened.ctx)
    assert got.resp_body == b"x" * (1024 * 1024)
    assert got.resp_body_ref is None  # stored inline, not spilled
    reopened.close()


def test_ciphertext_not_greppable(tmp_path):
    """The plaintext marker must not appear on disk in an encrypted db."""
    bundle = tmp_path / "enc5.nybiscan"
    proj = core_project.create_project(bundle, name="Enc5", passphrase=PASSPHRASE)
    marker = b"SUPER_SECRET_TOKEN_ABC123"
    proj.writer.enqueue(make_record(mime_type="text/plain", resp_body=marker))
    proj.writer.flush()
    proj.close()

    raw = (bundle / "session.db").read_bytes()
    assert marker not in raw
