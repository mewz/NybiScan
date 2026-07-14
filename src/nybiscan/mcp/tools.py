"""MCP tool logic (thin wrappers over the control API).

Each function takes a `Caller` and maps one tool to one API call, shaping the result for
the agent. NO enforcement here EXCEPT the agent-path bench scope-gate: MCP bench sends to
an out-of-scope target host are refused (the GUI's Bench is deliberately unrestricted
because a human clicks send; an autonomous agent is not that human-in-the-loop, so the
scope gate stands in). All other enforcement stays in the core.

Errors from the core are surfaced as ToolError with actionable messages (especially the
out-of-scope refusal). Tools hold no authorization logic of their own.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..core import scope as scope_mod
from . import bodies
from .caller import Caller, Result


class ToolError(RuntimeError):
    """A tool failure surfaced to the agent (the MCP SDK returns it as the tool error)."""


def _check(r: Result) -> Result:
    if not r.ok:
        d = r.detail()
        # Make any core scope refusal a consistent, actionable message for the agent.
        if "not in scope" in d.lower() and "retry" not in d.lower():
            d += " Add the host to scope in NybiScan, then retry. (Use get_scope to see what is in scope.)"
        raise ToolError(d)
    return r


def _scope_refusal(host: str) -> ToolError:
    return ToolError(
        f"Target host '{host}' is not in scope. Out-of-scope active actions are refused. "
        f"Ask the operator to add '{host}' to scope in NybiScan, then retry. "
        f"(Use get_scope to see what is currently in scope.)"
    )


def _scope_hosts(caller: Caller) -> set:
    r = _check(caller.request("GET", "/scope"))
    return {e["host"] for e in (r.body or [])}


# ----- read tools -----------------------------------------------------------


def list_history(caller: Caller, host: Optional[str] = None, limit: int = 200, offset: int = 0):
    """History summaries (optionally filtered to a domain). limit<=0 returns all."""
    r = _check(caller.request("GET", "/history", params={"host": host, "limit": limit, "offset": offset}))
    return r.body


def get_request_response(caller: Caller, entry_id: int, full: bool = False,
                         offset: int = 0, length: Optional[int] = None):
    """Full request + response for one entry, bodies DECODED to text. Large bodies
    return a capped preview with the total size; pass full=true or offset/length to
    read the rest (source is never hidden)."""
    d = _check(caller.request("GET", f"/history/{entry_id}")).body
    req_body = bodies.decode_body(
        d.get("req_body_b64"), dropped=d.get("req_body_dropped", False),
        content_encoding=d.get("req_content_encoding"), mime=d.get("req_mime_type"),
        full=full, offset=offset, length=length)
    resp_body = bodies.decode_body(
        d.get("resp_body_b64"), dropped=d.get("resp_body_dropped", False),
        content_encoding=d.get("resp_content_encoding"), mime=d.get("mime_type"),
        full=full, offset=offset, length=length)
    return {
        "id": d["id"], "method": d["method"], "scheme": d["scheme"], "host": d["host"],
        "port": d["port"], "url": d["url"], "status": d.get("status"),
        "mime_type": d.get("mime_type"), "source": d.get("source"),
        "capture_status": d.get("capture_status"),
        "request": {"headers_raw": d.get("req_headers_raw", ""), "body": req_body},
        "response": {"headers_raw": d.get("resp_headers_raw", ""), "body": resp_body},
    }


def get_sitemap(caller: Caller):
    """The host -> path tree over captured history (browser + spider + agent)."""
    return _check(caller.request("GET", "/sitemap")).body


def get_sitemap_host(caller: Caller, host: str):
    return _check(caller.request("GET", f"/sitemap/{host}")).body


def get_scope(caller: Caller):
    """The hosts currently in scope. Scope is human-owned: the agent cannot change it."""
    return _check(caller.request("GET", "/scope")).body


# ----- active tools (scope-gated) -------------------------------------------


def spider_start(caller: Caller, seed_entry_id: int, max_depth: Optional[int] = None,
                 exclude: Optional[List[dict]] = None, rate_limit_ms: Optional[int] = None,
                 max_requests: Optional[int] = None, include_binary: Optional[bool] = None):
    """Start a scope-gated crawl seeded from a captured request. An out-of-scope seed is
    refused by the core."""
    payload: Dict = {"seed_history_id": seed_entry_id}
    for k, v in (("max_depth", max_depth), ("exclude", exclude), ("rate_limit_ms", rate_limit_ms),
                 ("max_requests", max_requests), ("include_binary", include_binary)):
        if v is not None:
            payload[k] = v
    return _check(caller.request("POST", "/spider/start", json_body=payload)).body


def spider_stop(caller: Caller):
    return _check(caller.request("POST", "/spider/stop")).body


def spider_status(caller: Caller):
    return _check(caller.request("GET", "/spider/status")).body


def bench_create(caller: Caller, seed_entry_id: Optional[int] = None):
    """Create a Bench tab (optionally seeded from a captured request)."""
    payload = {"seed_history_id": seed_entry_id} if seed_entry_id is not None else {}
    return _check(caller.request("POST", "/bench/tabs", json_body=payload)).body


def _tab_host(caller: Caller, tab_id: int) -> str:
    tabs = _check(caller.request("GET", "/bench/tabs")).body or []
    for t in tabs:
        if t["id"] == tab_id:
            return t["conn_host"]
    raise ToolError(f"no such bench tab {tab_id}")


def bench_send(caller: Caller, tab_id: int, raw_request: Optional[str] = None,
               host: Optional[str] = None, port: Optional[int] = None,
               tls: Optional[bool] = None, autofill_cl: Optional[bool] = None):
    """Send a Bench tab's request verbatim. AGENT-PATH SCOPE GATE: the connection-bar
    target host (where the socket goes; the Host header is independent) must be in scope,
    else the send is refused. Response body is decoded to text."""
    patch: Dict = {}
    for k, v in (("raw_request", raw_request), ("conn_host", host), ("conn_port", port),
                 ("conn_tls", tls), ("content_length_autofill", autofill_cl)):
        if v is not None:
            patch[k] = v
    if patch:
        _check(caller.request("PATCH", f"/bench/tabs/{tab_id}", json_body=patch))

    target = host if host is not None else _tab_host(caller, tab_id)
    if not scope_mod.host_in_scope(_scope_hosts(caller), target):
        raise _scope_refusal(target)

    d = _check(caller.request("POST", f"/bench/tabs/{tab_id}/send")).body
    d["resp_body"] = bodies.decode_body(
        d.get("resp_body_b64"), content_encoding=d.get("resp_content_encoding"),
        mime=d.get("mime_type"))
    return d


def agent_fetch(caller: Caller, url: str, headers: Optional[Dict[str, str]] = None):
    """Fetch a URL through NybiScan (scope-gated in the core) so it lands in history +
    sitemap as agent-sourced. Response body is decoded to text."""
    body = {"url": url}
    if headers:
        body["headers"] = headers
    d = _check(caller.request("POST", "/agent/fetch", json_body=body)).body
    d["resp_body"] = bodies.decode_body(
        d.get("resp_body_b64"), dropped=d.get("resp_body_dropped", False),
        content_encoding=d.get("resp_content_encoding"), mime=d.get("mime_type"))
    return d
