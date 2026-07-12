# NybiScan Manual Tests

This file is the committed home for checks that cannot be pytested: things that
need a human, a browser, a real keychain, or an eyeball on process state. It
accumulates one section per plan. Later plans append; they never overwrite an
earlier plan's section.

## Why some checks are manual

Automated tests prove the code paths in isolation. They cannot prove that a real
browser trusts the exported CA, that live HTTPS traffic shows up in history, that
a pending row visibly flips to complete, that clean shutdown leaves no orphaned
process, or that a security guard behaves for a human driving the real CLI. Those
live here.

## How to run a section

Work top to bottom in a section. Each item states what to do, the exact command
or click path, and the explicit pass condition. Use a throwaway project under
/tmp so you never touch real engagement data. Activate the venv first with
source .venv/bin/activate.

## Machine-checkable convention (keep the grep-guard honest)

`tests/test_manual_tests_current.py` mechanically verifies that every command and
endpoint referenced here still exists in the code. For that guard to work:

- Write every CLI command the guard should check in backticks, starting with
  `nybiscan ` (for example `nybiscan proxy start`). The full command line may
  follow, flags and all.
- Write every API endpoint the guard should check in backticks as a single
  `/`-rooted token with no spaces and no dots (for example `/proxy/start`,
  `/history/{entry_id}`, `/ws/history`).
- Write filesystem paths (like /tmp/demo.nybiscan) inside the command backtick or
  without backticks, never as a standalone `/`-rooted backtick, so the guard does
  not mistake them for endpoints.

## Maintenance rule

If you change a CLI command, an API endpoint, a config path, an env var, or a
port default that appears here, update the matching item in the SAME change. A
stale manual-test step is a bug, not a documentation nicety. Bump the item's
"Verified" marker when you confirm it against the current build.

---

## Plan 1 - Core foundation + persistence

### 1.1 Install and full suite green
- What: install the package and run the automated suite.
- Command: `pip install -e ".[dev]"` then `pytest -q`
- Expected: install completes with no build errors; the suite reports all tests
  passed with no warnings.
- Verified: Plan 2.5

### 1.2 Create and inspect a plaintext project
- What: create a project bundle and read its metadata.
- Command: `nybiscan new /tmp/demo.nybiscan --name Demo` then
  `nybiscan info /tmp/demo.nybiscan`
- Expected: `info` prints JSON with name Demo and encrypted false. On disk the
  bundle contains session.db, project.toml, a ca/ dir, and a bodies/ dir.
- Verified: Plan 2.5

### 1.3 Encrypted project reopen (right and wrong passphrase)
- What: create an encrypted project and prove the passphrase gates access.
- Command: `nybiscan new /tmp/enc.nybiscan --encrypt` (enter a passphrase twice),
  then `nybiscan open /tmp/enc.nybiscan` once with the wrong passphrase and once
  with the right one.
- Expected: wrong passphrase fails with a clear error and a non-zero exit; right
  passphrase opens successfully. The encrypted bundle has NO bodies/ dir (all
  bodies stay in the encrypted db).
- Verified: Plan 2.5

### 1.4 Control API health and auth
- What: run the control API and probe it.
- Command: `nybiscan serve` in one shell, then `nybiscan health-check` in another.
- Expected: health-check prints PASS lines: `/health` reachable unauthenticated;
  an authed route returns 200 with the token and 401 without it; final RESULT
  PASS.
- Verified: Plan 2.5

### 1.5 runtime.json permissions
- What: confirm the control API writes its port and session token privately.
- Command: with `nybiscan serve` running, inspect
  `stat -f "%Sp" "$HOME/Library/Application Support/NybiScan/runtime.json"`
- Expected: permissions are `-rw-------` (0600).
- Verified: Plan 2.5

---

## Plan 2 - Proxy engine + capture

### 2.1 Install and suite green (mitmproxy present)
- What: confirm the proxy dependency installs and the suite passes.
- Command: `pip install -e ".[dev]"` then `pytest -q`
- Expected: mitmproxy installs from a prebuilt wheel; the suite passes.
- Verified: Plan 2.5

### 2.2 CA lifecycle and regenerate gate
- What: generate, export, and inspect the global CA, and confirm regeneration is
  guarded.
- Command: `nybiscan ca generate --global`, then
  `nybiscan ca export /tmp/nybiscan-ca.crt`, then `nybiscan ca info`, then run
  `nybiscan ca generate --global` a second time.
- Expected: the CA is created under ~/.nybiscan/ca (never ~/.mitmproxy); export
  writes a PEM certificate (public cert only, no private key); info prints the
  fingerprint and paths; the second generate prints a confirmation prompt warning
  that regenerating invalidates existing trust, and aborts unless you type
  regenerate.
- Verified: Plan 2.5

### 2.3 Live HTTPS capture through the proxy
- What: intercept real browser HTTPS traffic.
- Command: trust /tmp/nybiscan-ca.crt in your keychain or browser, then
  `nybiscan new /tmp/demo.nybiscan --name Demo` and
  `nybiscan proxy start --project /tmp/demo.nybiscan`. Point the browser proxy at
  127.0.0.1:8080, visit an https site, then in another shell run
  `nybiscan history` (and `nybiscan history --all` if there are many entries).
- Expected: the proxy prints its control API address, proxy address, and a CA
  install hint. Visited requests appear in history with scheme https, the right
  host and path, a status code, and capture status complete.
- Verified: Plan 2.5

### 2.4 Body filter (text kept, binary dropped)
- What: confirm the text-only default filter in the live path.
- Command: after 2.3, find an image or binary request and an html or json
  request in `nybiscan history`, then fetch each full entry with the authed
  `/history/{entry_id}` route (use the port and token from runtime.json).
- Expected: the binary/image entry keeps its metadata (mime, length) but has no
  stored response body (resp_body_dropped true, resp_body_b64 null); the
  html/json entry stores its body.
- Verified: Plan 2.5

### 2.5 Clean shutdown, no orphan
- What: confirm the proxy stops cleanly.
- Command: `nybiscan proxy stop` (or Ctrl-C in the proxy shell), then
  `pgrep -fl "nybiscan proxy start"`
- Expected: proxy stop reports running false; the WAL is checkpointed on close;
  no orphaned proxy process remains (the proxy is an in-process thread, so there
  is nothing separate to orphan).
- Verified: Plan 2.5

### 2.6 Security spot-check A: ssl_insecure guard
- What: prove unverified upstream TLS is off by default and only enabled under an
  explicit env guard.
- Command: with a project open and the control API running, read the port and
  token from the runtime file under ~/Library/Application Support/NybiScan. With
  NYBISCAN_ALLOW_INSECURE UNSET, send an authed POST to `/proxy/start` with body
  {"ssl_insecure": true} then an authed GET to `/proxy/status`. Then stop the
  proxy, export NYBISCAN_ALLOW_INSECURE=1, restart the proxy the same way, and
  check `/proxy/status` again.
- Expected: with the env unset, status reports ssl_insecure false (the guard
  rejected the request flag); with the env set, status reports ssl_insecure true.
  The guard is a real gate, off by default.
- Verified: Plan 2.5

### 2.7 Security spot-check B: WS token never in the URL
- What: prove the history WebSocket refuses a query-param token.
- Command: connect a WebSocket client to `/ws/history` three ways: with the token
  in a `?token=` query param; with an `Authorization: Bearer <token>` header; and
  with the token as the second `Sec-WebSocket-Protocol` value after nybiscan.
- Expected: the query-param connection is REJECTED (closed, code 1008); the header
  and subprotocol connections are accepted and then stream entry_created and
  entry_updated events.
- Verified: Plan 2.5

---

## Plan 3 - macOS Swift/SwiftUI GUI

Run from the repo (repo-dev launch). The GUI spawns the Python core; point it at
the venv core binary with NYBISCAN_BIN. Build the automated pieces first, then the
app.

### 3.1 Swift build and unit tests
- What: the client library and its tests build and pass from the CLI.
- Command: from gui/, run swift build and swift test.
- Expected: both succeed; the XCTest suite is green (API client request/decode,
  runtime.json reader, WebSocket header/subprotocol auth, health poll timeout,
  history model created-then-updated, core-process spawn errors).
- Verified: Plan 3

### 3.2 Build and launch the app
- What: assemble and launch the windowed app; the core spawns and connects.
- Command: from gui/, run scripts/make_app.sh, then open NybiScan.app. From the
  repo the app finds ../.venv/bin/nybiscan automatically (no env needed); if you
  move the .app out of the repo, set NYBISCAN_BIN to the nybiscan binary.
- Expected: a window appears. The app clears any stale runtime.json, spawns the
  core (nybiscan serve), polls `/health`, and reaches the project screen. If the
  core binary cannot be found, the app shows a clear "could not start the core"
  error instead of hanging.
- Verified: Plan 3

### 3.3 First-launch authorized-use gate
- What: the acknowledgment gates use and persists via the core.
- Command: on a fresh support dir (unset ack), launch the app; accept the gate.
  The app reads `/config` on launch and POSTs `/config/acknowledge` on accept.
- Expected: the authorized-use screen appears when authorized_use_ack is false;
  after accepting, the app proceeds and does not show the gate again on relaunch
  (the flag persisted to the core's config.toml).
- Verified: Plan 3

### 3.4 New, encrypted, and open projects
- What: project lifecycle via the API.
- Command: create a new plaintext project (name + location); create a new
  encrypted project (passphrase); open an existing bundle; try opening an
  encrypted bundle with the wrong passphrase.
- Expected: plaintext and encrypted projects create and open; the wrong
  passphrase surfaces the core's clear error (not a crash); the main window shows
  the project name.
- Verified: Plan 3

### 3.5 Live capture streams into the columnar table
- What: proxied traffic appears live in a spreadsheet-style table; pending flips
  to complete.
- Command: in Options, start the proxy on 127.0.0.1:8080 (`/proxy/start`); with
  the NybiScan CA trusted (from Plan 2), browse an https site through the proxy.
- Expected: the history table spans the FULL window width (top pane). Entries
  appear live over the WebSocket in a sortable Table with columns #, Host (with a
  lock icon for https), Method, URL, Status, Length, MIME, Ext, IP, Time. Host is
  wide enough to show at least `https://www.something.com` without clipping and
  URL/MIME are readable, while narrow columns (Status, Ext, Length, Method) stay
  tight. Real metadata is populated; a 304 and a no-extension URL render BLANK
  cells (not 0/null/broken). Clicking a column header sorts (Status, Method, Host,
  Time, Length). A pending row is visible first and flips to a completed status
  with mime/length. The "Live" indicator is green; if the core stops it shows
  "Live updates disconnected". Under busy capture the table stays responsive
  (throttled re-sort) and a selected row does not jump while new rows stream in.
- Verified: Plan 3

### 3.6 Tabbed detail, pending-aware and body-safe
- What: a tabbed Request/Response detail renders below the table; pending and
  binary handled.
- Command: click a row; use the Request and Response tabs. Also click a
  still-pending entry and a binary/image entry. The detail loads via
  `/history/{entry_id}`.
- Expected: the detail sits FULL WIDTH BELOW the table (bottom pane) and is blank
  when nothing is selected. It shows a Request tab and a Response tab, each with
  raw headers plus the decoded body. The active tab PERSISTS across selection:
  switch to Response, then arrow up/down through rows and each row shows its
  Response (the tab does not snap back to Request); switch to Request and it stays
  Request. A still-pending Response tab shows a waiting state and then populates; a
  dropped binary body shows a clear "body dropped" note; non-UTF-8 bodies show a
  hex preview rather than crashing; the UI never blocks while decoding.
- Large bodies render FULLY without interaction: select an entry with a large text
  body (e.g. a ~250KB or ~460KB text/javascript response), open the Response tab.
  The ENTIRE body paints immediately (no blank region below the first screenful),
  with NO need to select text or scroll first. Arrowing between large responses
  renders each fully without interaction, and the active tab still persists.
- Verified: Plan 3

### 3.10 Vertical layout and user-owned collapsible divider
- What: the table/detail split is top/bottom with a draggable, collapsible
  divider that only the user moves.
- Command: launch (split is ~50/50). Click a row. Drag the divider down so the
  detail is a sliver. Click several other rows; deselect and reselect; select a
  still-pending row.
- Expected: the divider drags freely up and down; the detail can be squashed to a
  sliver (table nearly full window) AND expanded large (detail most of the
  window); neither pane imposes a tall minimum that blocks this. Clicking the
  FIRST row does NOT move the divider. After dragging to a sliver, clicking other
  rows, deselecting/reselecting, and selecting a pending row all leave the divider
  EXACTLY where the user put it (it never snaps back to 50/50 or auto-grows).
  Selection changes only the detail CONTENT, never its height. (Cross-launch
  persistence of the divider and column widths is deferred.)
- Verified: Plan 3

### 3.7 Options panel: proxy status and CA info
- What: read-only status displays via the API.
- Command: open Options; read proxy status and CA info (`/proxy/status`,
  `/ca/info`).
- Expected: proxy status shows running and ssl_insecure false in normal use; CA
  info shows which CA resolves (project vs global), common name, and fingerprint.
  No generate/import/export controls this plan.
- Verified: Plan 3

### 3.8 Quit leaves no orphan
- What: clean shutdown of the spawned core.
- Command: quit the app (Cmd-Q) or send it SIGTERM; then
  pgrep -fl "nybiscan serve".
- Expected: no orphaned core or mitmproxy process remains. The core received
  SIGTERM, drained its writer, and checkpointed the WAL.
- Verified: Plan 3

### 3.9 Thin-client checks (code review)
- What: confirm the GUI stays a thin client.
- Command: review gui/Sources. Confirm the only shell-out is spawning the core
  (CoreProcess) plus lifecycle signals; every app operation (project, history,
  proxy, config, ca) is a control-API call; runtime.json is read fresh each
  connect (no cached port); the control-API port is never hardcoded; WebSocket
  auth uses the header/subprotocol, never a query param.
- Expected: all hold. No traffic parsing, body filtering, or store access in Swift.
- Verified: Plan 3

### 3.11 Proxy auto-start on open
- What: the proxy starts automatically on project open (default), controlled by a
  global flag, and fails visibly if it cannot start.
- Command: open a project (default flag on). Then in Options toggle
  "Auto-start proxy on project open" off (writes via `/config`) and reopen. Then
  turn it back on but occupy the listen port first (another listener on 8080) and
  open a project. On a first-ever launch (no global CA yet), open a project.
- Expected: with the flag on, opening a project auto-starts the proxy (via a
  `/config` read + `/proxy/start`) and capture streams with NO manual Start; the
  first requests are not missed (the live subscription connects before capture
  begins). With the flag off, the proxy does NOT auto-start (manual behavior). If
  auto-start cannot proceed (port in use), a clear visible "Auto-start proxy
  failed:" error appears, not a silent non-start. On a first-ever launch a
  non-blocking notice appears: a new CA was generated, export and trust it.
- Verified: Plan 3

### 3.12 Export and trust the CA from the UI
- What: export the public CA cert from Options so HTTPS interception works.
- Command: Options -> CA -> "Export PEM..." or "Export DER..." (calls
  `/ca/export`), choose a location in the save panel. Trust the exported cert
  (macOS keychain via security add-trusted-cert, or Firefox import). Browse an
  https site through the proxy.
- Expected: a PEM (.crt) or DER (.der) file containing the PUBLIC certificate is
  written (never the private key). After trusting it, https sites capture without
  cert errors. The note reminds that Firefox uses its own trust store. Generate
  and import remain CLI-only.
- Verified: Plan 3

---

## Plan 3.5 - Build orchestration + onboarding

### 3.5.1 One-command test surface
- What: the Makefile runs both toolchains.
- Command: `make test`
- Expected: pytest (Python core/api/cli) and swift test (Swift GUI) both run and
  pass from a single command.
- Verified: Plan 3.5

### 3.5.2 Fresh-clone gate (the real test)
- What: a stranger can go from clone to verified without knowing two toolchains.
- Command: clone the repo into a fresh directory (no .venv, no gui/.build, no
  NybiScan.app), then run only `make setup` and `make test`.
- Expected: `make setup` creates .venv at the repo root and installs deps, resolves
  SwiftPM; `make test` then reaches green from nothing. `make build` and `make run`
  launch the app and it locates the core (because .venv is at the exact path).
- Verified: Plan 3.5

### 3.5.3 Make-target guard has teeth
- What: a doc reference to a non-existent make target fails a test.
- Command: temporarily add a backticked reference to a bogus target (make plus a
  nonexistent name) to README.md and run the grep-guard
  (pytest tests/test_manual_tests_current.py); revert after.
- Expected: the guard FAILS while the bogus target is referenced and passes once
  reverted, so stale make-target docs cannot ship.
- Verified: Plan 3.5

---

## Plan 4 - Bench (Repeater analog)

### 4.1 Create, edit, and send a Bench request
- What: craft a request and send it verbatim, directly (not through the proxy).
- Command: open a project; switch to Bench (the History/Bench toggle); click + to
  create a tab. Set the connection bar (host:port + HTTPS checkbox) and edit the
  raw request (try an arbitrary METHOD like `FOOBAR` and a custom header). Press
  Send (Cmd-Return). The GUI calls `/bench/tabs` and `/bench/tabs/{id}/send`.
- Expected: the response renders in the lower pane (status, headers, decoded
  body); the send is recorded in the tab's history. Bench sends do NOT appear in
  the main History view (separation).
- Verified: Plan 4

### 4.2 Content-Length auto-fill toggle
- What: verbatim Content-Length control.
- Command: with "Auto C-L" ON, edit the body and send (Content-Length is
  recomputed to match). Turn "Auto C-L" OFF, set a deliberately-wrong
  Content-Length in the raw request, and send.
- Expected: with the toggle on, the sent Content-Length matches the body; with it
  off, the wrong value is sent exactly as typed (required for smuggling/desync
  tests). Nothing else in the request is altered either way.
- Verified: Plan 4

### 4.3 Connection bar is definitive; Host header is independent
- What: the socket target is the bar, not the Host header.
- Command: point the connection bar at one host:port but leave a DIFFERENT `Host:`
  header in the raw request. Send.
- Expected: Bench connects to the BAR's host:port and sends the typed Host header
  verbatim (never rewritten or synced). A mismatch is a supported test case.
- Verified: Plan 4

### 4.4 TLS does not verify
- What: Bench connects regardless of cert validity, like the proxy.
- Command: send an HTTPS request (HTTPS checkbox on) to a host with a self-signed
  or invalid certificate.
- Expected: the send succeeds and the response renders (no cert error, not
  blocked). A host that is unreachable / cannot complete the handshake shows a
  clear failure in the response pane instead.
- Verified: Plan 4

### 4.5 Send to Bench, tabs, per-tab history, persistence
- What: seed from capture, manage tabs, step history, persist across reopen.
- Command: in History, right-click a captured row -> "Send to Bench" (calls
  `/bench/tabs` seeded, opening a prefilled tab; a dropped binary body is noted).
  Rename a tab (right-click) and create several tabs. Send a tab a few times and
  step back/forth through its history via the response-pane `<` / `>` arrows AND the
  dropdown on the `<` control to jump directly to any send (uses
  `/bench/tabs/{id}/history` and `/bench/history/{entry_id}`). Quit and reopen the
  project.
- Expected: the seeded tab is prefilled with the captured request (editable);
  tabs rename/close; the arrows step one send at a time and the dropdown jumps to any
  send, each restoring BOTH the request editor and the response pane; after reopening
  the project, Bench tabs and their history PERSIST.
- Verified: Plan 4

### 4.6 Send/Cancel lifecycle: non-blocking, cancellable, bounded
- What: a send stays responsive; a hang is recoverable (Cancel) and bounded (timeout).
- Command: send a normal request and watch the Send button become Cancel with a
  spinner while in flight. Then turn "Auto C-L" OFF, set a Content-Length LARGER than
  the body (e.g. `Content-Length: 5000` on a tiny/empty body) so the server waits for
  bytes that never come, and Send. While it hangs, click Cancel (calls
  `/bench/tabs/{id}/cancel`). Separately, let one such send run without cancelling.
- Expected: the UI never freezes; clicking Cancel aborts the send promptly and the
  button returns to Send. A send left alone times out on its own. Either way the
  outcome is recorded as a new history entry (`cancelled` or `timeout`) that you can
  step to. The wrong Content-Length is NOT corrected; it goes out as typed.
- Verified: Plan 4

### 4.7 Send to Bench from the detail pane
- What: seed a Bench tab while reading a request in the detail view.
- Command: in History, select a row, then right-click inside the request/response
  detail text and choose "Send to Bench" (same seed as the row action).
- Expected: a prefilled Bench tab opens (connection bar + reconstructed raw request,
  h2 -> h1.1 rules, dropped-body noted); the detail pane's normal Copy/Paste are
  still present alongside "Send to Bench".
- Verified: Plan 4
