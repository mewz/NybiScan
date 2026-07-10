# CLAUDE.md

Guidance for working in this repo. Terse by design.

## What NybiScan is

A lightweight, project-based HTTP/HTTPS intercepting proxy for AUTHORIZED
penetration testing. A heavily skimmed-down Burp/ZAP focused on proxy history,
request replay, site mapping, and Claude-driven automation via MCP.

## Authorized-use constraint (non-negotiable)

For authorized security testing only. The app shows an authorized-use
acknowledgment on first launch per project and stores a per-project scope
(allowed host list). The spider and MCP-driven request features must refuse
targets outside the project scope by default. Do NOT add any capability designed
to evade detection, exfiltrate data, or attack out-of-scope hosts.

## Architecture principles

- STRICT separation. An OS-agnostic Python CORE (`src/nybiscan/core/`) owns all
  business logic: proxy engine, persistence, site model, replay, spider, MCP
  server. It exposes a LOCAL CONTROL API (`src/nybiscan/api/`): localhost-only
  HTTP + WebSocket, JSON. The Swift/SwiftUI GUI (`gui/`, future) is a thin CLIENT
  of that API. No business logic in the GUI.
- The core runs headless (CLI + API) with zero GUI dependencies importable.
  `nybiscan.core` must not import fastapi/uvicorn. A test enforces this.
- Project = a self-contained `.nybiscan` directory bundle. New and open both
  resolve to this store.
- Prefer well-supported libraries: mitmproxy (proxy, Plan 2), FastAPI + uvicorn
  (control API), SQLite/SQLCipher (storage), Pydantic (schemas), argon2-cffi
  (KDF).

## Storage model

- On-disk session format IS SQLite (WAL). Portable and cross-language, so a
  future Java/other UI can open it natively.
- `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`. One writer (the capture
  engine), many readers.
- BATCH writes. The capture engine pushes completed records onto an in-memory
  queue; a single writer thread flushes them in batched transactions (every
  ~100ms or every N records). Never one transaction per request.
- Large bodies (unencrypted only) over ~512 KB spill to `bodies/` referenced by
  sha256 (natural dedup). Metadata and small bodies stay in the db.
- Bundle layout:
  `<name>.nybiscan/ { session.db, ca/, bodies/, project.toml }`
- Before handoff/archive, run `PRAGMA wal_checkpoint(TRUNCATE)` so the bundle is
  self-contained. `close()` does this.
- Global settings live outside any project in
  `~/Library/Application Support/NybiScan/` as TOML.

## CA model (built in Plan 2, documented now)

- CA material is GLOBAL by default (`~/.nybiscan/ca/`) so the user trusts a CA
  once and reuses it across projects. Stored history is plaintext HTTP and
  CA-agnostic once captured.
- Resolution order at proxy start: project CA (`<bundle>/ca/`) if present, else
  global CA, else GENERATE into the global location.
- Support: bring your own CA (import), generate global CA (with confirmation if
  one exists, since regenerating invalidates trust), generate project CA
  (overrides global for that project), export the CA public cert for install.
  Never require exporting the private key to establish trust.
- Portability: a project relying on the global CA is not fully self-contained
  when zipped. Projects that must travel should use a project-specific CA.

## Encryption model

- Optional passphrase at project creation encrypts all session data at rest via
  SQLCipher (transparent AES-256), WAL mode like the plaintext path.
- Key: Argon2id(passphrase, per-db salt) -> 32-byte raw key -> SQLCipher raw-key
  mode. Params + salt (non-secret) live in `project.toml`; derive from STORED
  params on open. Passphrase/key never persisted; key in memory for the session.
- Encrypted projects keep ALL bodies in the db (no plaintext spill).
- Plaintext <-> encrypted conversion is an explicit export op, not a live toggle.
- The global CA in `~/.nybiscan/` is NOT covered by project encryption; it is
  protected by OS file permissions. Do not gate the CA behind the passphrase.

## Phased plan

1. Core foundation + persistence (THIS session, done): project store, schemas,
   SQLite WAL + batched writer, SQLCipher encrypted path, TOML config, control
   API skeleton (health + projects), CLI, pytest. No proxy, no GUI.
2. Proxy engine + capture (mitmproxy addon), CA generate/export/import, history
   over API + WebSocket.
3. macOS Swift/SwiftUI GUI (history).
4. Bench (replay) + match/replace + decompress.
5. Dashboard site map + scoped spider.
6. MCP server over the core.
7. Claude skill for MCP-driven source review + testing.

Do not start the next plan until the current test gate passes.

## Conventions

- No em dashes in generated docs (this file, DECISIONS.md, README.md).
- Keep the core import-clean. Business logic in core, not api/gui.
- Test what you change.
