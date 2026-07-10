# NybiScan GUI (placeholder)

The macOS front end is a native Swift/SwiftUI app (Plan 3+). It is a thin client
of the local control API only. It holds NO business logic.

The GUI talks to the Python core exclusively over the localhost control API
(HTTP + WebSocket, JSON), reading the port and per-session bearer token from:

    ~/Library/Application Support/NybiScan/runtime.json   (0600)

No Swift code exists yet. Do not add business logic here; it belongs in the
Python core so an alternate UI can reuse it.
