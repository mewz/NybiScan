"""NybiScan MCP server (Plan 6).

A thin peer-client of the localhost control API - the SAME API the Swift GUI uses - so
it inherits the core's scope-gating and rails automatically. Tool logic lives in
`tools.py` (testable via an injected Caller); `server.py` is the only module that imports
the MCP SDK (transport wiring).
"""
