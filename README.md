# NybiScan

A lightweight, project-based HTTP/HTTPS intercepting proxy for AUTHORIZED
penetration testing. Named after the owner's cat, Nybble.

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
- Python 3.11+ for the core.
- The GUI is currently a DEVELOPER artifact launched from the cloned repo. It is
  not yet a standalone distributable app (self-contained bundling, code-signing,
  and notarization are a later packaging plan).

## Running the app

The GUI spawns the Python core and then drives everything over the control API.
It locates the core by walking up from its executable to `<repo>/.venv/bin/nybiscan`,
so a Python environment MUST exist at the repo root named EXACTLY `.venv`. The
name and location matter.

From a fresh clone:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd gui && ./scripts/make_app.sh
open NybiScan.app
```

`scripts/make_app.sh` builds the Swift executable and wraps it in a clickable
`NybiScan.app` (Info.plist + binary). If the app reports "NybiScan core not
found", the `.venv` is missing or misnamed at the repo root; create it with the
commands above. (A `make setup` convenience layer is planned for a later pass; it
does not exist yet.)

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
  window; `swift build` and `swift test` run from `gui/`.

To intercept https you install and trust the NybiScan CA once (see the CA commands
below), then add it to your keychain or browser. The capture proxy and the control
API are separate listeners on separate ports; only the control API is
bearer-token authenticated.

## Tests

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
