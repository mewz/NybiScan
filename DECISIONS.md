# NybiScan Decisions

Terse log of locked decisions. Newest context lives in CLAUDE.md.

## Locked (product)

- Name: NybiScan (after the owner's cat, Nybble).
- Front end: native Swift/SwiftUI, a thin client over the local control API. No
  business logic in the GUI. Enables a cheap alternate UI later.
- Session format: `<name>.nybiscan` directory bundle (macOS document bundle).
- Storage: SQLite in WAL mode, one batched single-writer thread. Bodies over
  512 KB spill to `bodies/` (unencrypted projects only).
- Encryption: optional SQLCipher (AES-256, WAL), chosen at project creation.
  When encrypted, ALL bodies stay in the db (no `bodies/` spill), so there is a
  single encryption boundary. The 512 KB spill threshold does not apply to
  encrypted projects.
- KDF: Argon2id via argon2-cffi. Non-secret params (kdf, argon2_version, m_cost,
  t_cost, parallelism, salt) stored in `project.toml`. Key derived from STORED
  params+salt on open so reopen is deterministic. Passphrase and key never
  persisted; key held in memory for the session only. Lost passphrase = data
  unrecoverable. No backdoor.
- Config: TOML. Global config in `~/Library/Application Support/NybiScan/`;
  per-project `project.toml` in the bundle.
- CA: global-by-default (`~/.nybiscan/ca/`) with project override. Generate +
  export + import. Built in Plan 2; only documented now.
- Control API: FastAPI on `127.0.0.1`, dedicated auto-picked free port (NOT
  8080). Per-session bearer token required on every route except the
  unauthenticated `/health` liveness probe. Port + token written to
  `runtime.json` with 0600 perms.
- Proxy listener (Plan 2): default `127.0.0.1:8080`, IPv4, user-editable free
  text. Separate from the control API. Not built this session.
- Body filter default: capture only text-like bodies (text/*, html, json, xml,
  javascript, css). Binary/image bodies dropped (metadata kept, body omitted).

## Assumptions (Plan 1)

- Body-spill threshold: 512 KB. Unencrypted projects only.
- `export` command: implemented now as a JSONL dump (base64 bodies). Not stubbed.
  It is an interchange EXPORT, not the working store.
- Unknown/absent content type: body is kept (treated as text-like). Real binary
  responses carry an explicit content type.
- SQLCipher binding: `sqlcipher3==0.6.2`, which ships a prebuilt macOS wheel with
  SQLCipher bundled (no brew/system lib needed).
- Control API `/health` is unauthenticated; all project detail is authed-only.

## Scope guardrails (this session = Plan 1)

- No GUI code. No proxy/mitmproxy code. No CA generation code.
- `nybiscan.core` must import zero GUI/API frameworks.
