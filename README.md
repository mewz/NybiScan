# NybiScan

A lightweight, project-based HTTP/HTTPS intercepting proxy for AUTHORIZED
penetration testing. Named after the owner's cat, Nybble.

## Purpose

NybiScan aims to provide the proven manual-testing workflow of tools like Burp
Suite and OWASP ZAP - capture proxy history, inspect requests and responses, replay
and edit requests (Bench), and map and spider a target - in a smaller, native macOS
package built on an OS-agnostic core. It is for security testing of systems you are
explicitly authorized to test.

It additionally aims to expose an MCP server (planned) so that AI agents (Claude or
others) can interact with captured history and drive spidering and testing
programmatically. Those AI-driven capabilities are scoped to the same authorized-use
context as the rest of the tool: they are only for testing systems you are
authorized to test.

### Built today

- Intercepting HTTP/HTTPS proxy with live capture history.
- Request and response detail inspection.
- Bench: a repeater-style surface to replay and edit requests verbatim, with
  per-tab send history.
- Project persistence (a self-contained `.nybiscan` bundle, optionally encrypted).
- CA lifecycle (generate, import, export) for HTTPS interception.

### Roadmap (planned, not yet built)

- Dashboard site-map and scoped spider (Plan 5).
- MCP server over the core so AI agents can drive history and testing (Plan 6).
- A Claude skill for MCP-driven source review and testing (Plan 7).

## Authorized use only

NybiScan is for authorized security testing only. Use it only against systems you
own or have explicit written permission to test. It has no features for evading
detection, exfiltrating data, or attacking out-of-scope hosts, and never will.

## Status

Plans 1, 2, and 3 are done: the headless Python core and persistence layer, the
localhost control API, the in-process mitmproxy-based capture engine with the CA
lifecycle and a live history WebSocket, and a native macOS SwiftUI front end (a
thin client of the control API) with project new/open, a live history list,
request/response detail, and proxy control. See CLAUDE.md for the architecture and
phased plan, and DECISIONS.md for locked decisions.

## Requirements

- macOS with a Swift toolchain (Xcode) to build the GUI.
- Python 3.12+ for the core (built and verified on 3.12).
- The GUI is currently a DEVELOPER artifact launched from the cloned repo. It is
  not yet a standalone distributable app (self-contained bundling, code-signing,
  and notarization are a later packaging plan).

## Build architecture

NybiScan is a polyglot repo. A root Makefile orchestrates both toolchains so you
do not have to remember which command runs where:

```
Makefile (repo root)                     orchestrates both toolchains
  make setup  -> .venv at repo root + pip install -e ".[dev]" + swift package resolve
  make test   -> pytest (Python core/api/cli) + swift test (Swift GUI)
  make build  -> swift build + gui/scripts/make_app.sh
  make run    -> open gui/NybiScan.app
      |
      +-- src/nybiscan/  Python core + api + cli   (pytest)
      +-- gui/           Swift/SwiftUI app          (swift test)
            +-- scripts/make_app.sh  bundles NybiScan.app
```

## Running the macOS GUI app

From a fresh clone, the blessed path is `make setup`, then `make build`, then
`make run`; use `make test` any time to verify both suites.

`make setup` creates the Python environment at the repo root and installs deps.
`make build` compiles the Swift app and bundles a clickable `NybiScan.app`.
`make run` launches it.

The GUI is a developer artifact launched from the cloned repo. It spawns the
Python core and drives everything over the control API, locating the core by
walking up from its executable to `<repo>/.venv/bin/nybiscan`. So a Python
environment MUST exist at the repo root named EXACTLY `.venv` (the name and
location matter); `make setup` creates it there. If the app reports "NybiScan core
not found", the `.venv` is missing or misnamed at the repo root: run `make setup`.

The same steps by hand (what each make target does), if you prefer:

```
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd gui && ./scripts/make_app.sh
open NybiScan.app
```

## Architecture

- `src/nybiscan/core/` OS-agnostic core: schemas, crypto, storage, project
  lifecycle, proxy engine, CA. All business logic lives here. Imports no GUI/API
  frameworks.
- `src/nybiscan/api/` localhost control API (FastAPI). A thin layer over core.
- `src/nybiscan/cli/` command-line driver for the core.
- `gui/` native macOS SwiftUI app, a THIN CLIENT of the localhost control API. It
  spawns the core once, then drives project/history/proxy/config over HTTP +
  WebSocket. It holds no business logic (no traffic parsing, body filtering, or
  store access). Split into a testable `NybiScanKit` library and a `NybiScanApp`
  window.

To intercept https you install and trust the NybiScan CA once (see "Trusting the
CA" below). The capture proxy and the control API are separate listeners on
separate ports; only the control API is bearer-token authenticated.

## Tests

```
make test                 # both suites (the canonical check)
```

Or each toolchain on its own:

```
pytest -q                 # Python core + API (run from the repo root, venv active)
cd gui && swift test      # Swift client logic
```

## CLI

The core is also fully usable headless:

```
nybiscan new  /path/to/proj.nybiscan --name MyProj [--encrypt] [--scope example.com]
nybiscan open /path/to/proj.nybiscan
nybiscan info /path/to/proj.nybiscan
nybiscan export /path/to/proj.nybiscan out.jsonl
nybiscan serve            # runs the localhost control API
nybiscan health-check     # probes a running control API (PASS/FAIL)

# CA (global by default; ~/.nybiscan/ca)
nybiscan ca generate --global
nybiscan ca export /tmp/nybiscan-ca.crt        # public cert only; install/trust it
nybiscan ca info

# capture proxy (foreground; Ctrl-C or `nybiscan proxy stop` to stop)
nybiscan proxy start --project /path/to/proj.nybiscan   # default 127.0.0.1:8080
nybiscan history                                         # list entries (paged, default 200)
nybiscan history --all                                   # every entry
nybiscan history --limit 100 --offset 200                # page through
nybiscan proxy stop
```

An encrypted project cannot be recovered without its passphrase. There is no
backdoor.

## Trusting the CA (for https interception)

After exporting the public cert (`nybiscan ca export /tmp/nybiscan-ca.crt`), trust
it so your browser accepts the intercepted TLS. Only the public cert is trusted;
the private key never leaves `~/.nybiscan/ca`.

```
# macOS login keychain (per user; may prompt for your password)
security add-trusted-cert -r trustRoot \
  -k ~/Library/Keychains/login.keychain-db /tmp/nybiscan-ca.crt
```

For system-wide trust instead, run it with sudo against the System keychain:
`sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /tmp/nybiscan-ca.crt`.

Firefox uses its own trust store, not the system keychain. In Firefox, import the
same `/tmp/nybiscan-ca.crt` via Settings -> Privacy & Security -> Certificates ->
View Certificates -> Authorities -> Import, and trust it to identify websites.
