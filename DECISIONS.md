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

## Scope guardrails (Plan 1)

- No GUI code. No proxy/mitmproxy code. No CA generation code.
- `nybiscan.core` must import zero GUI/API frameworks.

## Locked (Plan 2)

- Proxy engine: mitmproxy 12.2.3 (pure-Python wheel), run IN-PROCESS as a
  DumpMaster on a dedicated thread with its own asyncio loop. Not a subprocess:
  the single-writer reuse constraint requires the addon to share the in-process
  BatchWriter. The capture addon enqueues INSERT/UPDATE ops onto that one writer;
  it never opens a db connection.
- pending -> complete/error persisted via INSERT on request, UPDATE on
  response/error, correlated by flow_id (mitmproxy flow id). Schema v1 -> v2 adds
  flow_id (indexed), req_content_encoding, resp_content_encoding. migrate() is
  transactional and idempotent; runs on open. Stale pending rows (from a prior
  hard kill) are swept to error on open.
- In-session abandoned flows (client disconnect mid-flight with no clean
  response/error hook) may remain pending until the next open, where the sweep
  marks them error. mitmproxy's error hook covers upstream failures/timeouts.
- Two listeners, never conflated: control API on 127.0.0.1 auto-picked port with
  bearer auth (unchanged); proxy on 127.0.0.1:8080 default (project.toml [listen],
  IPv4, user-editable), no token (it speaks HTTP proxy protocol to browsers).
- Proxy lifecycle: `nybiscan proxy start --project P` runs foreground (opens
  project, starts proxy, prints addrs + CA hint, blocks). Clean shutdown (Ctrl-C
  or POST /proxy/stop) drains the writer and checkpoints the WAL via
  Project.close. `proxy stop` stops only the proxy component.
- CA: mitmproxy CertStore under ~/.nybiscan/ca/ (global default) or <bundle>/ca/
  (project override), NEVER ~/.mitmproxy/. Global dir overridable via
  NYBISCAN_CA_DIR (used by tests to stay hermetic). Resolution: project CA if
  present, else global, else generate into global. Regenerating a global CA
  requires explicit confirmation (invalidates existing trust). Export ships the
  public cert only (PEM/DER); never the private key.
- ssl_insecure (unverified upstream TLS) defaults False and is honored ONLY when
  NYBISCAN_ALLOW_INSECURE is set; its effective value is surfaced in
  GET /proxy/status. Test-only; never a normal-use option.
- WebSocket /ws/history auth is via Authorization header or the "nybiscan" token
  subprotocol, NOT a ?token= query param (no secrets in URLs). Events:
  entry_created then entry_updated, creates published before updates per flush.
- Read connection opened with check_same_thread=False (control API dispatches
  across a threadpool; SQLite/SQLCipher are serialized builds). Writer keeps its
  own dedicated write connection (single-writer invariant intact).
- pydantic pinned <2.12: mitmproxy 12.2.3 caps typing-extensions<=4.14 while
  pydantic>=2.12 needs >=4.14.1. Capping keeps all deps on prebuilt wheels.

## Scope guardrails (Plan 2)

- No GUI. No Bench/replay. No dashboard/spider. No MCP. Later plans.
- Reuse Plan 1 (BatchWriter, filters, schemas, repository, Project.close);
  extensions are additive, not forks.

## Locked (Plan 2.5)

- Manual checks that cannot be pytested live in MANUAL_TESTS.md, one accumulating
  section per plan, each item stating what to do, the exact command, the pass
  condition, and a "Verified" plan marker.
- Machine-checkable convention: commands the guard verifies are backticked and
  start with "nybiscan "; endpoints are backticked single "/"-rooted tokens with
  no spaces and no dots. Filesystem paths are never standalone "/"-rooted
  backticks (so the guard does not mistake them for endpoints).
- Maintenance rule recorded in CLAUDE.md: a change to any referenced command,
  endpoint, config path, env var, or port default updates the matching entry in
  the same change; a plan is not gate-passed until MANUAL_TESTS.md matches the
  build.
- tests/test_manual_tests_current.py is the grep-guard. It introspects the LIVE
  argparse parser (subcommand tree) and FastAPI app (walking
  _IncludedRouter.original_router so the WebSocket route is seen) to check that
  every referenced command/endpoint still exists. Existence only, not behavior.
  No duplicate hardcoded list.

## Locked (Plan 3)

- First native front end is a macOS SwiftUI app under gui/, a SwiftPM package
  with a testable NybiScanKit library (models, API client, runtime.json reader,
  WebSocket auth/decode, history model, health poller, core-process supervisor)
  and a thin NybiScanApp executable (the window). swift build / swift test are
  CLI-driven. scripts/make_app.sh wraps the built binary in a clickable
  NybiScan.app (Info.plist + binary); a real distributable .app that locates a
  bundled Python core is a later concern.
- Thin client: zero business logic in Swift. The ONLY shell-out is spawning the
  core (nybiscan serve) plus lifecycle signals to that owned process. Every app
  operation goes through the control API. runtime.json (port + token) is read
  fresh on every connect; the control-API port is never cached or hardcoded.
  WebSocket auth is the Authorization header or the nybiscan Sec-WebSocket-Protocol
  subprotocol, never a query param.
- Core supervision: the GUI spawns the core via NYBISCAN_BIN (default the repo
  venv nybiscan; repo-dev launch only), polls for runtime.json then GET /health.
  On quit (Cmd-Q via applicationWillTerminate, or SIGTERM/SIGINT via a dispatch
  signal source), it SIGTERMs the core (drain + WAL checkpoint) and escalates to
  SIGKILL after a grace period. Verified: no orphaned core after quit.
- Additive API for the GUI (thin wrappers over existing core, tested):
  GET /config + POST /config/acknowledge (authorized-use flag, owned by the core,
  not the client; /config also prefills the options listen fields) and read-only
  GET /ca/info (which CA resolves, without generating). Core helpers added:
  ca.resolve_existing_confdir (non-generating) and a NYBISCAN_SUPPORT_DIR env
  override on config.app_support_dir so config/runtime tests stay hermetic.
- Options panel scope: interactive proxy start/stop + listen ip/port; read-only
  proxy status and CA info. Filters, match/replace, and decompress are OMITTED
  (no backing config state yet; they return when actually configurable).
- Detail bodies are base64 in the API; the GUI decodes OFF the main thread, caps
  very large bodies, and falls back to a hex preview for non-UTF-8. Display
  handling only, not business logic.
