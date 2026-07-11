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
request/response detail, and proxy control. See gui/README.md to build the app,
CLAUDE.md for the architecture and phased plan, and DECISIONS.md for locked
decisions.

To intercept https you install and trust the NybiScan CA once (`nybiscan ca
generate --global`, `nybiscan ca export ...`, then add it to your keychain or
browser). The capture proxy and the control API are separate listeners on
separate ports; only the control API is bearer-token authenticated.

## Architecture

- `src/nybiscan/core/` OS-agnostic core: schemas, crypto, storage, project
  lifecycle. All business logic lives here. Imports no GUI/API frameworks.
- `src/nybiscan/api/` localhost control API (FastAPI). A thin layer over core.
- `src/nybiscan/cli/` command-line driver for the core.
- `gui/` future Swift/SwiftUI client (placeholder).

## Dev setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

## CLI

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
