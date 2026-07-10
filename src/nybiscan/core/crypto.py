"""Argon2id passphrase-to-key derivation for encrypted projects.

The derived 32-byte key is passed to SQLCipher in raw-key mode. The passphrase
and key are never written to disk; only the (non-secret) Argon2id parameters and
per-database salt live in project.toml.
"""

from __future__ import annotations

import secrets

from argon2.low_level import Type, hash_secret_raw

from .schemas import KdfParams

KEY_LEN = 32  # bytes -> 256-bit SQLCipher key
SALT_LEN = 16  # bytes


def default_kdf_params() -> KdfParams:
    """Fresh params with a random salt. Called once at project creation."""
    return KdfParams(
        kdf="argon2id",
        argon2_version=19,
        m_cost=65536,  # 64 MiB
        t_cost=3,
        parallelism=4,
        salt=secrets.token_bytes(SALT_LEN).hex(),
    )


def derive_key(passphrase: str, params: KdfParams) -> bytes:
    """Derive the raw SQLCipher key from a passphrase and stored params."""
    if params.kdf != "argon2id":
        raise ValueError(f"unsupported kdf: {params.kdf!r}")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=params.salt_bytes,
        time_cost=params.t_cost,
        memory_cost=params.m_cost,
        parallelism=params.parallelism,
        hash_len=KEY_LEN,
        type=Type.ID,
        version=params.argon2_version,
    )
