"""MCP server wiring (the ONLY module that imports the MCP SDK).

Registers the NybiScan tools with authorized-use-framed descriptions over stdio, each
backed by a fresh HttpCaller (read from runtime.json, so a core restart with a new token
is picked up). All tool LOGIC lives in tools.py; this file is pure transport wiring.

NybiScan is for AUTHORIZED penetration testing only. These tools operate against a project
the human operator has opened, and active tools are scope-gated by the NybiScan core: the
human owns what is in scope, the model reasons about how to test within it.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from . import tools
from .caller import HttpCaller

mcp = FastMCP("nybiscan")


def _caller() -> HttpCaller:
    # Fresh per call: reads runtime.json so a NybiScan restart (new port/token) works.
    return HttpCaller()


@mcp.tool()
def list_history(host: Optional[str] = None, limit: int = 200, offset: int = 0):
    """List captured HTTP history for authorized testing (proxy, spider, and agent
    traffic). Optionally filter to a domain with `host`. `limit<=0` returns all. Returns
    summaries; use get_request_response for full source."""
    return tools.list_history(_caller(), host=host, limit=limit, offset=offset)


@mcp.tool()
def get_request_response(entry_id: int, full: bool = False, offset: int = 0,
                         length: Optional[int] = None):
    """Get the full request and response for a captured entry, with bodies DECODED to
    text (actual JSON/HTML/JS source, not base64). Large bodies return a capped preview
    with the total size; pass full=true or offset/length to read the rest."""
    return tools.get_request_response(_caller(), entry_id, full=full, offset=offset, length=length)


@mcp.tool()
def get_sitemap():
    """Get the site map: a host -> path tree over all captured history."""
    return tools.get_sitemap(_caller())


@mcp.tool()
def get_sitemap_host(host: str):
    """Get the site-map path tree for a single host."""
    return tools.get_sitemap_host(_caller(), host)


@mcp.tool()
def get_scope():
    """List the hosts currently in scope. Scope is the human-owned authorized-testing
    boundary; the agent cannot change it. Active tools are refused for out-of-scope
    targets - relay 'please add host X to scope' to the operator when blocked."""
    return tools.get_scope(_caller())


@mcp.tool()
def spider_start(seed_entry_id: int, max_depth: Optional[int] = None,
                 exclude: Optional[List[Dict]] = None, rate_limit_ms: Optional[int] = None,
                 max_requests: Optional[int] = None, include_binary: Optional[bool] = None):
    """Start a scoped crawl seeded from a captured request (authorized testing). Crawls
    only in-scope hosts from the seed path downward, with the core's rails. An out-of-scope
    seed is refused. `exclude` is a list of {pattern, is_regex}."""
    return tools.spider_start(_caller(), seed_entry_id, max_depth=max_depth, exclude=exclude,
                              rate_limit_ms=rate_limit_ms, max_requests=max_requests,
                              include_binary=include_binary)


@mcp.tool()
def spider_stop():
    """Stop the running spider."""
    return tools.spider_stop(_caller())


@mcp.tool()
def spider_status():
    """Get spider status: running, found, saved, cap, current target."""
    return tools.spider_status(_caller())


@mcp.tool()
def bench_create(seed_entry_id: Optional[int] = None):
    """Create a Bench tab for crafting/replaying a request (optionally seeded from a
    captured entry). Edit and send it with bench_send."""
    return tools.bench_create(_caller(), seed_entry_id=seed_entry_id)


@mcp.tool()
def bench_send(tab_id: int, raw_request: Optional[str] = None, host: Optional[str] = None,
               port: Optional[int] = None, tls: Optional[bool] = None,
               autofill_cl: Optional[bool] = None):
    """Send a Bench tab's request verbatim for authorized testing. The connection host/
    port is the definitive target (the Host header is independent). The target host must
    be IN SCOPE or the send is refused. Response body is decoded to text."""
    return tools.bench_send(_caller(), tab_id, raw_request=raw_request, host=host, port=port,
                            tls=tls, autofill_cl=autofill_cl)


@mcp.tool()
def agent_fetch(url: str, headers: Optional[Dict[str, str]] = None):
    """Fetch a URL through NybiScan for authorized testing so it lands in history + the
    site map as agent-sourced traffic. The URL host must be IN SCOPE or it is refused.
    Response body is decoded to text."""
    return tools.agent_fetch(_caller(), url, headers=headers)


def run() -> None:
    """Run the MCP server over stdio (the standard transport for Claude Code)."""
    mcp.run(transport="stdio")
