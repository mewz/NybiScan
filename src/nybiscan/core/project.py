"""Project bundle lifecycle: new / open / close.

A project is a self-contained `<name>.nybiscan/` directory bundle:

    myproject.nybiscan/
      session.db      SQLite (WAL) or SQLCipher: history, sites, scope, meta
      ca/             optional per-project CA override (populated in Plan 2)
      bodies/         large spilled bodies (UNENCRYPTED projects only)
      project.toml    project-level config (name, scope, listen, encryption)
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import List, Optional

from . import config, crypto
from .errors import (
    PassphraseRequiredError,
    ProjectExistsError,
    ProjectNotFoundError,
)
from .events import EventHub
from .filters import StorageContext
from .schemas import KdfParams, ProjectMeta
from .store import db, repository
from .store.writer import BatchWriter

BUNDLE_SUFFIX = ".nybiscan"
SESSION_DB = "session.db"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_bundle(path: Path | str) -> Path:
    p = Path(path).expanduser()
    if p.suffix != BUNDLE_SUFFIX:
        p = p.with_name(p.name + BUNDLE_SUFFIX)
    return p


class Project:
    """An open project: a read connection, a batched writer, and config."""

    def __init__(
        self,
        bundle: Path,
        toml_data: dict,
        read_conn,
        writer: BatchWriter,
        ctx: StorageContext,
        events: EventHub,
    ) -> None:
        self.bundle = bundle
        self.toml = toml_data
        self.read_conn = read_conn
        self.writer = writer
        self.ctx = ctx
        self.events = events

    @property
    def is_encrypted(self) -> bool:
        return self.ctx.is_encrypted

    @property
    def session_db(self) -> Path:
        return self.bundle / SESSION_DB

    def listen_settings(self) -> tuple[str, int]:
        """Proxy listen ip/port from project.toml, falling back to defaults."""
        listen = self.toml.get("listen", {}) or {}
        return str(listen.get("ip", "127.0.0.1")), int(listen.get("port", 8080))

    def ca_confdir(self) -> Path:
        """The project's CA override directory (may not exist yet)."""
        return self.bundle / "ca"

    def meta(self) -> ProjectMeta:
        return repository.read_project_meta(self.read_conn)

    def close(self) -> None:
        # Close the reader first so the writer's checkpoint can TRUNCATE the WAL.
        try:
            self.read_conn.close()
        finally:
            self.writer.close()


def _build_ctx(bundle: Path, encrypted: bool) -> StorageContext:
    return StorageContext(
        is_encrypted=encrypted,
        bodies_dir=None if encrypted else (bundle / "bodies"),
    )


def create_project(
    path: Path | str,
    name: Optional[str] = None,
    scope: Optional[List[str]] = None,
    passphrase: Optional[str] = None,
) -> Project:
    """Create a new .nybiscan bundle and return it opened.

    If passphrase is provided the session db is SQLCipher-encrypted and no
    bodies/ directory is used (all bodies stay inside the encrypted db).
    """
    bundle = _normalize_bundle(path)
    if bundle.exists():
        raise ProjectExistsError(f"Project already exists: {bundle}")

    name = name or bundle.stem
    scope = scope or []
    encrypted = passphrase is not None

    bundle.mkdir(parents=True)
    (bundle / "ca").mkdir()
    if not encrypted:
        (bundle / "bodies").mkdir()

    key: Optional[bytes] = None
    kdf_params: Optional[KdfParams] = None
    if encrypted:
        kdf_params = crypto.default_kdf_params()
        key = crypto.derive_key(passphrase, kdf_params)

    proj_uuid = str(uuid.uuid4())
    created = _now_ms()

    conn = db.open_connection(bundle / SESSION_DB, key, check_same_thread=True)
    try:
        db.create_schema(conn)
        repository.init_meta(conn, name, proj_uuid, created, encrypted)
        repository.set_scope(conn, scope)
    finally:
        conn.close()

    toml_data = {
        "project": {
            "name": name,
            "uuid": proj_uuid,
            "created_ts": created,
            "scope": scope,
        },
        "listen": {"ip": "127.0.0.1", "port": 8080},
        "encryption": _encryption_block(encrypted, kdf_params),
    }
    config.write_project_toml(bundle, toml_data)

    return open_project(bundle, passphrase=passphrase)


def _encryption_block(encrypted: bool, params: Optional[KdfParams]) -> dict:
    if not encrypted or params is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "kdf": params.kdf,
        "argon2_version": params.argon2_version,
        "m_cost": params.m_cost,
        "t_cost": params.t_cost,
        "parallelism": params.parallelism,
        "salt": params.salt,
    }


def open_project(path: Path | str, passphrase: Optional[str] = None) -> Project:
    """Open an existing .nybiscan bundle.

    Raises PassphraseRequiredError for an encrypted project opened without a
    passphrase, and WrongPassphraseError (from the db layer) on a bad passphrase.
    """
    bundle = _normalize_bundle(path)
    if not bundle.is_dir() or not (bundle / "project.toml").exists():
        raise ProjectNotFoundError(f"Not a NybiScan project bundle: {bundle}")

    toml_data = config.read_project_toml(bundle)
    enc = toml_data.get("encryption", {}) or {}
    encrypted = bool(enc.get("enabled"))

    key: Optional[bytes] = None
    if encrypted:
        if not passphrase:
            raise PassphraseRequiredError(
                "This project is encrypted; a passphrase is required to open it."
            )
        params = KdfParams(
            kdf=enc.get("kdf", "argon2id"),
            argon2_version=int(enc.get("argon2_version", 19)),
            m_cost=int(enc.get("m_cost", 65536)),
            t_cost=int(enc.get("t_cost", 3)),
            parallelism=int(enc.get("parallelism", 4)),
            salt=enc["salt"],
        )
        # Derive once from the STORED params/salt; reuse for both connections.
        key = crypto.derive_key(passphrase, params)

    ctx = _build_ctx(bundle, encrypted)
    session_db = str(bundle / SESSION_DB)

    # Reader connection. check_same_thread=False because the control API dispatches
    # requests across a threadpool and the lifespan shutdown closes on another
    # thread; SQLite/SQLCipher are built serialized so this is safe. Wrong
    # passphrase still fails here first.
    read_conn = db.open_connection(session_db, key, check_same_thread=False)

    # Bring an older (v1) bundle up to date, then sweep any pending rows left by
    # a prior hard kill (no live capture is producing them at open time).
    db.migrate(read_conn)
    repository.mark_pending_interrupted(read_conn)

    events = EventHub()
    writer = BatchWriter(session_db, key, ctx, event_hub=events)

    return Project(bundle, toml_data, read_conn, writer, ctx, events)
