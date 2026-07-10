"""NybiScan CLI.

Commands:
  new <path> [--name N] [--encrypt] [--scope H ...]   create a project bundle
  open <path>                                          open (validate) a project
  info <path>                                          print project metadata
  export <path> <out.jsonl>                            dump history to JSONL
  serve [--port P]                                     run the control API
  health-check                                         probe a running control API
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request

from ..core import export as core_export
from ..core import project as core_project
from ..core.errors import NybiScanError, WrongPassphraseError


def _prompt_new_passphrase() -> str:
    while True:
        p1 = getpass.getpass("New passphrase: ")
        p2 = getpass.getpass("Confirm passphrase: ")
        if not p1:
            print("Passphrase cannot be empty.", file=sys.stderr)
            continue
        if p1 != p2:
            print("Passphrases do not match; try again.", file=sys.stderr)
            continue
        return p1


def _open_maybe_encrypted(path: str):
    """Open a project, prompting for a passphrase only if required."""
    try:
        return core_project.open_project(path)
    except core_project.PassphraseRequiredError:
        passphrase = getpass.getpass("Passphrase: ")
        return core_project.open_project(path, passphrase=passphrase)


def cmd_new(args: argparse.Namespace) -> int:
    passphrase = _prompt_new_passphrase() if args.encrypt else None
    try:
        proj = core_project.create_project(
            args.path, name=args.name, scope=args.scope or [], passphrase=passphrase
        )
    except NybiScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    meta = proj.meta()
    proj.close()
    print(f"Created project '{meta.name}' at {proj.bundle}")
    print(f"  encrypted: {meta.encrypted}")
    print(f"  uuid:      {meta.uuid}")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    try:
        proj = _open_maybe_encrypted(args.path)
    except (NybiScanError, WrongPassphraseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    meta = proj.meta()
    proj.close()
    print(f"Opened '{meta.name}' (records: {meta.record_count}, encrypted: {meta.encrypted})")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    try:
        proj = _open_maybe_encrypted(args.path)
    except (NybiScanError, WrongPassphraseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    meta = proj.meta()
    proj.close()
    print(json.dumps(meta.model_dump(), indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    try:
        proj = _open_maybe_encrypted(args.path)
    except (NybiScanError, WrongPassphraseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        n = core_export.export_jsonl(proj, args.out)
    finally:
        proj.close()
    print(f"Exported {n} records to {args.out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from ..api.server import serve

    serve(port=args.port)
    return 0


def cmd_health_check(args: argparse.Namespace) -> int:
    """Probe a running control API using runtime.json. Prints PASS/FAIL."""
    from ..api.server import read_runtime

    try:
        port, token = read_runtime()
    except FileNotFoundError:
        print("FAIL: runtime.json not found; is `nybiscan serve` running?", file=sys.stderr)
        return 1

    base = f"http://127.0.0.1:{port}"
    ok = True

    # 1) /health unauthenticated -> 200
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
            body = json.loads(r.read())
        assert r.status == 200 and body.get("status") == "ok"
        print(f"PASS: /health reachable unauthenticated -> {body}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL: /health probe: {exc}", file=sys.stderr)

    # 2) authed route WITH token -> 200
    try:
        req = urllib.request.Request(
            f"{base}/projects/current", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        print("PASS: /projects/current with token -> 200")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL: authed route with token: {exc}", file=sys.stderr)

    # 3) authed route WITHOUT token -> 401
    try:
        urllib.request.urlopen(f"{base}/projects/current", timeout=5)
        ok = False
        print("FAIL: /projects/current without token did NOT return 401", file=sys.stderr)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("PASS: /projects/current without token -> 401")
        else:
            ok = False
            print(f"FAIL: expected 401 without token, got {exc.code}", file=sys.stderr)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nybiscan", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a project bundle")
    p_new.add_argument("path")
    p_new.add_argument("--name", default=None)
    p_new.add_argument("--encrypt", action="store_true")
    p_new.add_argument("--scope", nargs="*", default=None)
    p_new.set_defaults(func=cmd_new)

    p_open = sub.add_parser("open", help="open (validate) a project")
    p_open.add_argument("path")
    p_open.set_defaults(func=cmd_open)

    p_info = sub.add_parser("info", help="print project metadata")
    p_info.add_argument("path")
    p_info.set_defaults(func=cmd_info)

    p_export = sub.add_parser("export", help="dump history to JSONL")
    p_export.add_argument("path")
    p_export.add_argument("out")
    p_export.set_defaults(func=cmd_export)

    p_serve = sub.add_parser("serve", help="run the control API")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    p_hc = sub.add_parser("health-check", help="probe a running control API")
    p_hc.set_defaults(func=cmd_health_check)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
