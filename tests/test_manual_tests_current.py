"""Grep-guard: every command/endpoint referenced in MANUAL_TESTS.md still exists.

This checks EXISTENCE, not behavior. Full behavior stays manual by nature; this
guard just kills the cheapest rot: a renamed or deleted command/endpoint that a
manual step still tells a human to run. It introspects the LIVE argparse parser
and FastAPI app, so there is no second hardcoded list that could itself go stale.

See the "Machine-checkable convention" section of MANUAL_TESTS.md for how
references must be written (backticked `nybiscan ...` commands; backticked
single-token `/`-rooted endpoints).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from nybiscan.api.app import create_app
from nybiscan.api.state import AppState
from nybiscan.cli.__main__ import build_parser

MANUAL_TESTS = Path(__file__).resolve().parents[1] / "MANUAL_TESTS.md"

_BACKTICK = re.compile(r"`([^`]+)`")


# ----- what the doc references ----------------------------------------------


def _referenced(text: str):
    cli, endpoints = set(), set()
    for span in _BACKTICK.findall(text):
        span = span.strip()
        if span.startswith("nybiscan"):
            tokens = span.split()[1:]  # drop the program name
            # command words are the tokens before the first flag/option
            cmd = []
            for tok in tokens:
                if tok.startswith("-"):
                    break
                cmd.append(tok)
            if cmd:
                cli.add(tuple(cmd))
        elif span.startswith("/") and " " not in span and "." not in span and span != "/":
            endpoints.add(_normalize_path(span))
    return cli, endpoints


def _normalize_path(path: str) -> str:
    # Collapse path params ({id}, <id>) to a single wildcard so /history/{entry_id}
    # matches the route template regardless of the param name used in the doc.
    path = re.sub(r"\{[^}]+\}", "*", path)
    path = re.sub(r"<[^>]+>", "*", path)
    return path


# ----- what the code actually provides --------------------------------------


def _real_cli_commands() -> set:
    """Leaf command paths (those with a func handler) from the live parser."""
    leaves = set()

    def walk(parser, prefix):
        subactions = [
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        ]
        if not subactions:
            if prefix:
                leaves.add(tuple(prefix))
            return
        for action in subactions:
            for name, subparser in action.choices.items():
                walk(subparser, prefix + [name])

    walk(build_parser(), [])
    return leaves


def _real_routes() -> set:
    """All route path templates, incl. the WebSocket route hidden behind
    _IncludedRouter (which app.openapi() omits)."""
    app = create_app(AppState("guard"))
    paths = set()

    def walk(routes):
        for route in routes:
            p = getattr(route, "path", None)
            if p:
                paths.add(_normalize_path(p))
            inner = getattr(route, "original_router", None)
            if inner is not None and getattr(inner, "routes", None):
                walk(inner.routes)

    walk(app.routes)
    return paths


# ----- the guard ------------------------------------------------------------


def test_manual_tests_reference_real_commands_and_endpoints():
    assert MANUAL_TESTS.exists(), "MANUAL_TESTS.md is missing"
    cli_refs, endpoint_refs = _referenced(MANUAL_TESTS.read_text())

    # Sanity: the doc must actually reference something, or the guard is a no-op.
    assert cli_refs, "no `nybiscan ...` commands found in MANUAL_TESTS.md"
    assert endpoint_refs, "no `/...` endpoints found in MANUAL_TESTS.md"

    real_cli = _real_cli_commands()
    real_routes = _real_routes()

    bad_cli = []
    for ref in cli_refs:
        # a reference is valid if its 2-token or 1-token prefix is a real command
        if tuple(ref[:2]) not in real_cli and tuple(ref[:1]) not in real_cli:
            bad_cli.append("nybiscan " + " ".join(ref))

    bad_endpoints = [ref for ref in endpoint_refs if ref not in real_routes]

    assert not bad_cli, (
        "MANUAL_TESTS.md references CLI commands that do not exist: "
        f"{bad_cli}. Real commands: {sorted(' '.join(c) for c in real_cli)}"
    )
    assert not bad_endpoints, (
        "MANUAL_TESTS.md references API endpoints that do not exist: "
        f"{bad_endpoints}. Real routes: {sorted(real_routes)}"
    )
