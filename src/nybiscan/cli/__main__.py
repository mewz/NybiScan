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

from ..core import ca as core_ca
from ..core import config as core_config
from ..core import export as core_export
from ..core import project as core_project
from ..core.errors import CaExistsError, NybiScanError, WrongPassphraseError


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


# ----- control-API client helpers (for proxy stop / history) ----------------


def _api_request(method: str, path: str, body: dict | None = None):
    from ..api.server import read_runtime

    port, token = read_runtime()
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def _ca_confdir_for(project_path: str | None) -> "object":
    from pathlib import Path

    if project_path:
        return core_project._normalize_bundle(project_path) / "ca"
    return core_ca.global_ca_dir()


# ----- proxy -----------------------------------------------------------------


def cmd_proxy_start(args: argparse.Namespace) -> int:
    from ..api.proxy_control import start_proxy
    from ..api.server import serve

    bundle = core_project._normalize_bundle(args.project)
    try:
        toml_data = core_config.read_project_toml(bundle)
    except FileNotFoundError:
        print(f"error: not a NybiScan project: {bundle}", file=sys.stderr)
        return 1
    encrypted = bool((toml_data.get("encryption", {}) or {}).get("enabled"))
    passphrase = getpass.getpass("Passphrase: ") if encrypted else None

    def _startup(state):
        project = core_project.open_project(bundle, passphrase=passphrase)
        state.attach_project(project)
        status = start_proxy(
            state, ip=args.ip, port=args.port, ssl_insecure=args.ssl_insecure
        )
        ca_cert = f"{status['ca_dir']}/{core_ca.CA_CERT_PEM}"
        print(f"Proxy listening on http://{status['listen_host']}:{status['listen_port']}")
        print(f"Install CA (trust this to intercept https): {ca_cert}")
        if status.get("ssl_insecure"):
            print("WARNING: ssl_insecure is ON (upstream TLS not verified) - test use only")
        print("Press Ctrl-C or run `nybiscan proxy stop` to stop the proxy.")

    serve(on_startup=_startup)
    return 0


def cmd_proxy_stop(args: argparse.Namespace) -> int:
    try:
        result = _api_request("POST", "/proxy/stop")
    except FileNotFoundError:
        print("error: no running control API (runtime.json missing)", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"error: could not reach control API: {exc}", file=sys.stderr)
        return 1
    print(f"proxy stopped (running={result.get('running')})")
    return 0


# ----- ca --------------------------------------------------------------------


def cmd_ca_generate(args: argparse.Namespace) -> int:
    confdir = _ca_confdir_for(args.project) if args.project else core_ca.global_ca_dir()
    scope = "project" if args.project else "global"
    try:
        core_ca.generate(confdir, force=False)
    except CaExistsError:
        print(f"A {scope} CA already exists at {confdir}.", file=sys.stderr)
        print("Regenerating INVALIDATES existing trust; you must re-install and", file=sys.stderr)
        print("re-trust the new CA in every browser/keychain.", file=sys.stderr)
        answer = input("Type 'regenerate' to proceed: ").strip()
        if answer != "regenerate":
            print("aborted.")
            return 1
        core_ca.generate(confdir, force=True)
    print(f"CA generated at {confdir}")
    print(f"Public cert to install: {confdir}/{core_ca.CA_CERT_PEM}")
    return 0


def cmd_ca_import(args: argparse.Namespace) -> int:
    confdir = _ca_confdir_for(args.project) if args.project else core_ca.global_ca_dir()
    core_ca.import_ca(cert_path=args.cert, key_path=args.key, confdir=confdir)
    print(f"CA imported to {confdir}")
    return 0


def cmd_ca_export(args: argparse.Namespace) -> int:
    confdir = _ca_confdir_for(args.project) if args.project else core_ca.global_ca_dir()
    try:
        out = core_ca.export_cert(confdir, args.out, fmt=args.format)
    except NybiScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"exported {args.format} cert to {out}")
    return 0


def cmd_ca_info(args: argparse.Namespace) -> int:
    confdir = _ca_confdir_for(args.project) if args.project else core_ca.global_ca_dir()
    try:
        info = core_ca.ca_info(confdir)
    except NybiScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2))
    return 0


# ----- history (client) ------------------------------------------------------


def cmd_history(args: argparse.Namespace) -> int:
    path = "/history?limit=%d" % args.limit
    if args.host:
        path += "&host=%s" % args.host
    try:
        rows = _api_request("GET", path)
    except FileNotFoundError:
        print("error: no running control API (runtime.json missing)", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        print(f"error: {exc.code} {exc.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    for r in rows:
        print(
            f"{r['id']:>5}  {r['capture_status']:<8} {str(r['status'] or '-'):>3}  "
            f"{r['method']:<6} {r['scheme']}://{r['host']}:{r['port']}{r['url']}  "
            f"[{r['mime_type'] or '-'}]"
        )
    print(f"({len(rows)} entries)")
    return 0


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

    # proxy start/stop
    p_proxy = sub.add_parser("proxy", help="run or stop the capture proxy")
    proxy_sub = p_proxy.add_subparsers(dest="proxy_command", required=True)
    p_pstart = proxy_sub.add_parser("start", help="open a project and run the proxy (foreground)")
    p_pstart.add_argument("--project", required=True)
    p_pstart.add_argument("--ip", default=None)
    p_pstart.add_argument("--port", type=int, default=None)
    p_pstart.add_argument(
        "--ssl-insecure",
        dest="ssl_insecure",
        action="store_true",
        help="do not verify upstream TLS (test only; needs NYBISCAN_ALLOW_INSECURE=1)",
    )
    p_pstart.set_defaults(func=cmd_proxy_start)
    p_pstop = proxy_sub.add_parser("stop", help="stop the proxy on a running control API")
    p_pstop.set_defaults(func=cmd_proxy_stop)

    # ca generate/import/export/info
    p_ca = sub.add_parser("ca", help="manage the intercept CA")
    ca_sub = p_ca.add_subparsers(dest="ca_command", required=True)

    p_cagen = ca_sub.add_parser("generate", help="generate a CA")
    g = p_cagen.add_mutually_exclusive_group()
    g.add_argument("--global", dest="is_global", action="store_true", help="global CA (default)")
    g.add_argument("--project", default=None, help="generate a project-specific CA")
    p_cagen.set_defaults(func=cmd_ca_generate)

    p_caimp = ca_sub.add_parser("import", help="import an existing CA cert + key")
    p_caimp.add_argument("--cert", required=True)
    p_caimp.add_argument("--key", required=True)
    p_caimp.add_argument("--project", default=None)
    p_caimp.set_defaults(func=cmd_ca_import)

    p_caexp = ca_sub.add_parser("export", help="export the public CA cert")
    p_caexp.add_argument("out")
    p_caexp.add_argument("--format", choices=["pem", "der"], default="pem")
    p_caexp.add_argument("--project", default=None)
    p_caexp.set_defaults(func=cmd_ca_export)

    p_cainfo = ca_sub.add_parser("info", help="show CA details")
    p_cainfo.add_argument("--project", default=None)
    p_cainfo.set_defaults(func=cmd_ca_info)

    # history (client)
    p_hist = sub.add_parser("history", help="list captured history via the control API")
    p_hist.add_argument("--host", default=None)
    p_hist.add_argument("--limit", type=int, default=200)
    p_hist.set_defaults(func=cmd_history)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
