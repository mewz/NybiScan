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

## CA model (built in Plan 2)

Implemented in `core/ca.py`, driven by CLI `nybiscan ca ...`. The global CA dir
is overridable via `NYBISCAN_CA_DIR`, and the app-support dir (config.toml,
runtime.json) via `NYBISCAN_SUPPORT_DIR`. Tests set both to temp dirs to stay
hermetic and never touch the real user config or CA.

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

1. Core foundation + persistence (done): project store, schemas, SQLite WAL +
   batched writer, SQLCipher encrypted path, TOML config, control API skeleton
   (health + projects), CLI, pytest. No proxy, no GUI.
2. Proxy engine + capture (done): in-process mitmproxy addon writing via the
   Plan 1 BatchWriter (schema v2: flow_id + content_encoding; pending -> complete
   /error), CA generate/export/import, history over authed REST + a
   /ws/history WebSocket. Proxy listener is separate from the control API.
2.5. Manual-test checklist system (done): MANUAL_TESTS.md plus a grep-guard test
   (tests/test_manual_tests_current.py) that verifies referenced commands and
   endpoints still exist. Docs infrastructure only, no behavior change.
3. macOS Swift/SwiftUI GUI (done): SwiftPM package under gui/ (testable
   NybiScanKit library + thin NybiScanApp window). Thin client over the control
   API: project new/open, live history (backfill + WebSocket), pending-aware
   detail, options (proxy control + read-only status/CA info). Added additive API
   GET/POST /config and GET /ca/info. Addendum completed the history UI: a
   core-derived `extension` field (schema v3), a sortable columnar Table, a
   reusable tabbed Request/Response detail (for Plan 4 Bench reuse), a user-owned
   vertical split, proxy auto-start (default on), persistent detail tab, and CA
   export from the UI. Plan 3 COMPLETE.
3.5. Build orchestration (done): a root Makefile (make setup/test/build/run) is the
   canonical surface across both toolchains; README build diagram; grep-guard checks
   README make-targets exist. Future plan gates run `make test`. NEXT is Plan 4
   (Bench).
4. Bench (Repeater analog) (done): craft/edit/send requests verbatim (direct
   low-level HTTP/1.1 send, not through the proxy; TLS no-verify like the proxy),
   multiple renamable tabs + per-tab send history persisted in the bundle (schema
   v4), send-to-Bench seeding from capture, Content-Length auto-fill toggle. Core
   owns the send engine + storage; GUI reuses the editable request/response surface.
   New /bench/* API. Finisher complete: server-side cancellable send (Send <->
   Cancel, bounded timeout recorded as error='timeout'/'cancelled'), append-only
   per-tab history with Burp-style `<`/`>` + direct-pick navigation restoring both
   panes, and detail-pane "Send to Bench" parity. NEXT is Plan 5.
5. Dashboard site map + scope + scoped spider (done): a passive site-map (host -> path
   tree queried over the shared history table, mapped nodes only), minimal scope
   management (per-host in-scope list with per-host stored session headers; add/update-
   session/remove; add-to-scope from row + detail), and a scope-gated seed-based spider
   (schema v5: history.source + spider_run_id, scope.headers). The spider records
   DIRECTLY into the shared history via the single writer tagged source=spider (never
   through the proxy), crawls any in-scope host from the seed path downward using each
   host's own stored session, and ships the mandatory rails (start-confirmation, safe
   rate limit via interruptible wait, hard request cap, prompt Stop, absolute exclude
   list checked before every fetch, out-of-scope refusal). beautifulsoup4 for link/form
   extraction (JS rendering deferred). New /sitemap, /scope, /spider/* API. NEXT is
   Plan 6.
6. MCP server over the core.
7. Claude skill for MCP-driven source review + testing.

Do not start the next plan until the current test gate passes.

## Manual tests (MANUAL_TESTS.md)

Some checks cannot be automated (browser CA trust, live HTTPS capture, no orphan
process, human-driven security guards). They live in MANUAL_TESTS.md, one
accumulating section per plan.

Maintenance rule (definition-of-done, not a soft reminder):

- Any change to a CLI command, API endpoint, config path, env var, or port
  default that appears in MANUAL_TESTS.md REQUIRES updating the matching entry in
  the SAME change. A stale manual-test step is a bug, not a documentation nicety.
- Every plan's gate includes: append that plan's manual checks to
  MANUAL_TESTS.md, fix any entry the plan invalidated, and bump the entry's
  "Verified" marker. A plan is not gate-passed until MANUAL_TESTS.md reflects the
  current build.
- tests/test_manual_tests_current.py mechanically fails if a referenced command
  or endpoint no longer exists. It checks existence only; behavior stays manual.

## Conventions

- No em dashes in generated docs (this file, DECISIONS.md, README.md,
  MANUAL_TESTS.md).
- Keep the core import-clean. Business logic in core, not api/gui.
- Test what you change.
