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
