# NybiScan

A lightweight, project-based HTTP/HTTPS intercepting proxy for AUTHORIZED
penetration testing. Named after the owner's cat, Nybble.

## Authorized use only

NybiScan is for authorized security testing only. Use it only against systems you
own or have explicit written permission to test. It has no features for evading
detection, exfiltrating data, or attacking out-of-scope hosts, and never will.

## Status

Plan 1 (this session): the headless Python core and persistence layer, plus a
localhost control API skeleton and a CLI. No proxy engine and no GUI yet (later
plans). See CLAUDE.md for the architecture and the full phased plan, and
DECISIONS.md for locked decisions.

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
```

An encrypted project cannot be recovered without its passphrase. There is no
backdoor.
