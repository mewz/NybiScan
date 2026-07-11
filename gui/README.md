# NybiScan GUI (macOS, SwiftUI)

The native front end. A thin client of the localhost control API: it renders
state and calls endpoints, and holds no business logic. All app logic lives in
the Python core.

## Layout

- `Sources/NybiScanKit/` testable client logic (no window): Codable models, the
  control-API client, the runtime.json reader, WebSocket auth + event decoding,
  the history model, the health poller, and the core-process supervisor.
- `Sources/NybiScanApp/` the SwiftUI window (`@main` app + views + AppModel).
- `Tests/NybiScanKitTests/` XCTest over NybiScanKit (hermetic, URLProtocol stub).
- `scripts/make_app.sh` wraps the built binary into a clickable `NybiScan.app`.

## Build, test, run

```
cd gui
swift build
swift test
scripts/make_app.sh
NYBISCAN_BIN="$PWD/../.venv/bin/nybiscan" open NybiScan.app
```

The GUI spawns the Python core (`nybiscan serve`) as its one shell-out, then
talks to it over the control API. Point `NYBISCAN_BIN` at the core binary (the
repo venv by default). Everything else (project open, proxy control, history,
config, CA info) is an API call. The control-API port and token are read fresh
from `runtime.json` each launch.

## Scope (Plan 3)

Project new/open, live history list (backfill + WebSocket), pending-aware
request/response detail, and an options panel (proxy start/stop + listen ip/port,
read-only proxy status and CA info). Bench, dashboard/spider, and editable
filters/match-replace are later plans.
