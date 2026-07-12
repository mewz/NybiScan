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

## Locked (Plan 3 cleanup)

- ONE project README at the repo root owns the whole story (both toolchains, core
  + GUI relationship, run/launch). gui/README.md is reduced to a one-line pointer;
  no per-directory README duplicates content.
- Launch contract: NybiScan.app is a DEVELOPER artifact launched from the cloned
  repo. It REQUIRES a Python environment at the repo root named exactly `.venv`;
  the app locates the core by walking up to `<repo>/.venv/bin/nybiscan`. When the
  core binary cannot be located, the app fails fast with an ACTIONABLE error
  (CoreProcess.notFoundMessage) naming the expected `.venv` path and the setup
  commands, distinct from the health-timeout message (which only fires after the
  binary was located and launched). Standalone self-contained bundling (no repo
  `.venv`) is deferred to a later packaging plan.

## Locked (Plan 3 addendum: columnar history + tabbed detail)

- Core-vs-client derivation principle: a field lives in CORE if a second thin
  client would have to reimplement logic to match it (define once, all clients
  read the same value); it may live in the CLIENT if a second client would
  trivially re-derive it as pure display.
- `extension` (file extension parsed from the URL path) is CORE: real parsing edge
  cases (query-strip, last-segment-only, dotfiles, empty candidate, numeric
  version/date rejection, length cap) defined once in `capture.parse_extension`,
  stored on the record, exposed in `/history`. Plan 5 spider / Plan 6 MCP will
  query it. Schema v2 -> v3 adds the `extension` column; `migrate()` generalized
  to add any missing post-v1 column (tested v1->v3 and v2->v3, plaintext and
  encrypted-through-cipher).
- `has_params` (URL has a query string) is CLIENT-derived (Swift `hasParams`);
  trivial display, nothing downstream queries it, no core column. `isSecure`
  (https) and `statusSort` (Optional status made sortable) are likewise
  client-only display derivations.
- History list is a sortable SwiftUI Table; re-sort is throttled (not per WS
  event) and selection is bound to a stable entry id so an open detail does not
  jump while rows stream. Legitimately-empty fields render blank.
- The request/response detail is a REUSABLE `RequestResponseView` (Request /
  Response tabs, Raw only) built with an `editable` flag reserved so Plan 4 Bench
  reuses the same component with an editable Request tab.

## Locked (Plan 3 layout addendum)

- The history UI is a vertical (top/bottom) split: the table spans the full window
  width on top, the detail spans the full width below. Data-table + inspector
  model, not a navigation master-detail sidebar.
- The divider is a CUSTOM user-owned split, not SwiftUI `VSplitView`. `VSplitView`
  derives its position from child content sizes, so selecting a row (detail grows
  from the empty state) snapped the divider. Instead the bottom (detail) pane's
  height is a single `@State` fraction written ONLY by the drag gesture; the
  0.5 default applies once at launch and thereafter the divider holds where the
  user dragged it. Selection changes the detail pane's CONTENT, never its HEIGHT
  (DetailView identity is stable; its height comes from the fraction). No
  selection, deselection, reselection, or pending/complete transition ever moves
  the divider.
- The detail pane is ALWAYS present (stable layout), blank when nothing is
  selected. The divider drags freely and both panes collapse to a sliver at both
  extremes (no tall minimum blocks the scan-then-read workflow).
- Column widths are by importance/content: Host has a hard min floor (~220pt) that
  fits a full https domain before truncating; Host and URL flex to absorb extra
  window width; MIME/IP/Time are medium-fixed (fit application/javascript,
  255.255.255.255, the timestamp); Method/Status/Length/Ext/# are narrow fixed and
  never steal width from Host/URL.
- Deferred: column REORDERING (drag to rearrange), and cross-launch PERSISTENCE of
  divider position and column widths. Within-session stability is the requirement;
  cross-launch is a later pass.

## Locked (Plan 3 final cleanup: auto-start + tab memory + CA export)

- `auto_start_proxy` is a global config flag, DEFAULT ON, owned by the core
  (config.py) and exposed via GET /config + POST /config. On project open the GUI
  reads it and, if on, calls the existing /proxy/start with the configured listen
  ip/port. Auto-start subscribes the live history stream BEFORE starting capture so
  early requests are not missed. It fails VISIBLY ("Auto-start proxy failed: ...")
  on unmet preconditions, distinct from "flag off = no attempt". If auto-start had
  to generate a new global CA (none existed), a non-blocking notice points the user
  to export + trust it. No proxy logic in the GUI.
- The active detail tab (Request/Response) is model-owned view state
  (DetailUIState in Kit); selecting a row updates the selection but never the tab,
  so it persists across selection (same user-owned pattern as the divider). The
  select() nil-flap was removed so the detail view is not destroyed/reset.
- The raw request/response body is rendered with an NSTextView (RawTextView
  NSViewRepresentable), not a SwiftUI Text in a ScrollView: SwiftUI Text did not
  get a fresh layout/redraw when a large decoded string was assigned async, so
  large bodies stayed blank until a selection/scroll forced a redraw. NSTextView
  handles large text; on update we set the string and force layout + display.
- CA export is surfaced in the UI (Options): POST /ca/export wraps the existing
  core export and returns the PUBLIC cert only (PEM or DER, base64); the GUI owns
  the save dialog, the core owns the cert material, and the private key NEVER
  leaves the core (test-guarded). CA generate/import stay CLI-only. The UI notes
  that Firefox uses its own trust store.

## Backlog (deferred, do not build yet)

- Binary-in-history VIEW FILTER (hide binary/image/css rows like Burp's filter
  bar): needs a display-filter (hide but still capture/store) vs capture-filter
  (do not record) decision. Lands with the editable-filters options UI.
- History columns/detail deferred: Comment (needs a write surface + storage),
  Edited (only meaningful once Bench exists), Cookies (Plan 5 session work),
  Headers/Hex detail sub-tabs (Raw only for now), and any request editing in the
  detail (that is Bench, Plan 4).

- Plan 3.5: a root Makefile (`make setup` creates `.venv` at the exact
  path/name; `make test` runs pytest + swift test; `make build` runs swift build +
  make_app.sh; `make run` launches), a build-architecture diagram in the README,
  and extending the grep-guard to check that README make-targets exist in the
  Makefile. Until then, do NOT document Makefile targets as usable.
- Packaging plan: bundle Python + core + SQLCipher into NybiScan.app
  (self-contained, no repo `.venv`), code-sign + notarize, so the app launches
  outside the repo by double-click.

## Locked (Plan 3.5: build orchestration)

- A root Makefile is the canonical build/test surface across both toolchains. It
  WRAPS existing mechanisms (pip, swift, gui/scripts/make_app.sh); it does not
  reimplement builds or bundling. `make setup` creates `.venv` at the exact
  repo-root path/name the GUI depends on.
- `make test` (pytest + swift test) is THE gate command; future plan gates run it
  instead of two separate commands.
- The README build diagram shows both toolchains and is kept honest by a grep-guard
  extension: every backticked `make <target>` in README/MANUAL_TESTS must be a real
  target in the Makefile (introspected live, no duplicate list).
- No `Package.resolved` yet: there are no external SwiftPM dependencies. If one is
  added later, keep `Package.resolved` tracked (it is a lockfile, not an artifact).

## Locked (Plan 4: Bench)

- Bench (Repeater analog; named "Bench", never "Repeater") sends DIRECTLY via a
  core HTTP client, NOT through the proxy. Bench sends record only in the tab's own
  bench_history, never the main proxy history (avoids double-recording / clutter).
- Send is UNRESTRICTED (not scope-gated): Bench is a manual, one-request-at-a-time
  tool, so the human is the per-send authorization check. Scope gating is for
  AUTOMATED active testing (spider/MCP/fuzzer) in later plans; Bench is
  intentionally not behind it.
- Send fidelity = VERBATIM, low-level (core/bench/engine.py writes raw bytes to a
  plain/TLS socket via stdlib sockets; the response framing is read with
  http.client). No high-level client, no injected/normalized headers. The
  connection target is the tab's host/port/tls (the connection bar), NEVER derived
  from the Host header; a bar-vs-Host mismatch is a supported test case (vhost
  fuzzing, LB routing, SSRF-to-internal). Free-text METHOD.
- Content-Length auto-fill is a toggle (default on) that touches ONLY
  Content-Length; off sends it exactly as typed (smuggling/desync).
- Send protocol = HTTP/1.1 only; HTTP/2 send deferred (binary/HPACK). TLS offers
  http/1.1 via ALPN and does NOT verify certs (connects regardless of cert
  validity, like the proxy upstream); a completed handshake with a bad cert is not
  an error, but a genuine connection/handshake failure lands in bench_history.error.
  No tls_verified recording; TLS posture analysis is out of scope.
- Bench stores the FULL response body (the text-only capture filter does not apply;
  it is an explicit single request). Response body stored decoded + original
  content-encoding recorded (shared core/decode.py), like capture.
- Send is SYNCHRONOUS (send -> wait -> show response); async-with-pending is not
  needed for a single deliberate request.
- Persistence: bench_tabs + bench_history in the .nybiscan bundle (schema v3 -> v4;
  migrate CREATEs the tables, transactional + idempotent, tested plaintext +
  encrypted). bench_tabs stores raw_request text + connection metadata (no
  structured header columns; raw text is the wire source of truth). Encrypted
  projects keep Bench bodies in-db.
- Writes use the single-writer BatchWriter via a new submit(fn) primitive (runs on
  the writer thread synchronously, returns a result); no competing db connection.
- Send-to-Bench seeds a tab from a capture: h1.1 request used as-is; h2 (version
  HTTP/2.0, no Host header) is reconstructed to h1.1 by normalizing the request-line
  version and injecting a Host from the captured host[:port]; a dropped binary body
  is noted (cannot replay). Reconstruction is a seeding convenience only; edits +
  send stay byte-verbatim.
- GUI reuses the editable request/response surface: an EditableRawTextView (raw
  request) + the read-only RawTextView (response), a connection bar, and a
  History/Bench section toggle. Thin client: no HTTP-sending or business logic in
  Swift.
