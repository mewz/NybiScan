"""CA lifecycle.

CA material is GLOBAL by default (~/.nybiscan/ca/) so the user installs/trusts
once and reuses across projects. A project may override with its own bundle
ca/ dir. The CA is used only live, at capture time, to sign leaf certs; stored
history is plaintext HTTP and CA-agnostic once captured.

The CA lives in ~/.nybiscan/ca/ or <bundle>/ca/, NEVER ~/.mitmproxy/. We wrap
mitmproxy's CertStore, which uses the "mitmproxy-ca*" basename inside a confdir:

    mitmproxy-ca.pem        private key + cert (used live to sign leaves)
    mitmproxy-ca-cert.pem   public cert only (PEM, for install into trust store)
    mitmproxy-ca-cert.cer   public cert only (DER)

Resolution at proxy start: project CA if present, else global, else GENERATE
into global. Never require exporting the private key to establish trust.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from .errors import CaExistsError, CaNotFoundError

_BASENAME = "mitmproxy"
_KEY_SIZE = 2048


def global_ca_dir() -> Path:
    """The global CA directory.

    Defaults to ~/.nybiscan/ca. Overridable via the NYBISCAN_CA_DIR env var so
    tests stay hermetic and never touch the user's real home.
    """
    override = os.environ.get("NYBISCAN_CA_DIR")
    if override:
        return Path(override)
    return Path.home() / ".nybiscan" / "ca"

CA_KEYCERT = "mitmproxy-ca.pem"  # key + cert (private material)
CA_CERT_PEM = "mitmproxy-ca-cert.pem"  # public cert (PEM)
CA_CERT_DER = "mitmproxy-ca-cert.cer"  # public cert (DER)


def ca_exists(confdir: Path) -> bool:
    return (confdir / CA_KEYCERT).exists()


def generate(confdir: Path, force: bool = False) -> Path:
    """Generate a CA into confdir. Refuses to overwrite an existing CA unless force."""
    confdir = Path(confdir)
    if ca_exists(confdir) and not force:
        raise CaExistsError(
            f"A CA already exists at {confdir}. Regenerating invalidates existing "
            "trust; you must re-install and re-trust the new CA. Pass force to proceed."
        )
    confdir.mkdir(parents=True, exist_ok=True)
    from mitmproxy import certs

    certs.CertStore.create_store(confdir, _BASENAME, _KEY_SIZE)
    return confdir / CA_KEYCERT


def generate_global(force: bool = False) -> Path:
    return generate(global_ca_dir(), force=force)


def generate_project(bundle: Path, force: bool = False) -> Path:
    return generate(Path(bundle) / "ca", force=force)


def resolve_confdir(bundle: Optional[Path]) -> Path:
    """Project CA if present, else global, else generate into global."""
    if bundle is not None:
        proj = Path(bundle) / "ca"
        if ca_exists(proj):
            return proj
    gdir = global_ca_dir()
    if ca_exists(gdir):
        return gdir
    generate(gdir, force=False)
    return gdir


def resolve_existing_confdir(bundle: Optional[Path]) -> Optional[Path]:
    """Like resolve_confdir but NEVER generates. Returns the CA that would apply
    (project override, else global), or None if neither exists. For read-only
    callers (e.g. GET /ca/info) that must not create a CA as a side effect."""
    if bundle is not None:
        proj = Path(bundle) / "ca"
        if ca_exists(proj):
            return proj
    gdir = global_ca_dir()
    if ca_exists(gdir):
        return gdir
    return None


def import_ca(cert_path: Path, key_path: Path, confdir: Path) -> Path:
    """Import an existing CA (bring your own): write key+cert as mitmproxy-ca.pem.

    mitmproxy expects the private key followed by the cert in one PEM. We then
    load it via CertStore so the derived public cert files are materialized.
    """
    confdir = Path(confdir)
    confdir.mkdir(parents=True, exist_ok=True)
    key_pem = Path(key_path).read_bytes()
    cert_pem = Path(cert_path).read_bytes()
    combined = key_pem.rstrip() + b"\n" + cert_pem.rstrip() + b"\n"
    (confdir / CA_KEYCERT).write_bytes(combined)

    from mitmproxy import certs

    store = certs.CertStore.from_store(confdir, _BASENAME, _KEY_SIZE)
    # Materialize the public cert files for export/install.
    (confdir / CA_CERT_PEM).write_bytes(store.default_ca.to_pem())
    return confdir / CA_KEYCERT


def public_cert_bytes(confdir: Path, fmt: str = "pem") -> bytes:
    """Return the PUBLIC CA certificate bytes (PEM or DER). Never the private key."""
    confdir = Path(confdir)
    if not ca_exists(confdir):
        raise CaNotFoundError(f"No CA at {confdir}")
    from mitmproxy import certs

    store = certs.CertStore.from_store(confdir, _BASENAME, _KEY_SIZE)
    if fmt == "pem":
        return store.default_ca.to_pem()
    if fmt == "der":
        from cryptography.hazmat.primitives.serialization import Encoding

        return store.default_ca.to_cryptography().public_bytes(Encoding.DER)
    raise ValueError(f"unsupported export format: {fmt!r}")


def export_cert(confdir: Path, out_path: Path, fmt: str = "pem") -> Path:
    """Export the PUBLIC CA certificate (never the private key) for install."""
    confdir = Path(confdir)
    if not ca_exists(confdir):
        raise CaNotFoundError(f"No CA at {confdir}")
    out = Path(out_path)
    if fmt == "pem":
        src = confdir / CA_CERT_PEM
        if not src.exists():
            from mitmproxy import certs

            store = certs.CertStore.from_store(confdir, _BASENAME, _KEY_SIZE)
            out.write_bytes(store.default_ca.to_pem())
            return out
        shutil.copyfile(src, out)
    elif fmt == "der":
        from cryptography.hazmat.primitives.serialization import Encoding
        from mitmproxy import certs

        store = certs.CertStore.from_store(confdir, _BASENAME, _KEY_SIZE)
        out.write_bytes(store.default_ca.to_cryptography().public_bytes(Encoding.DER))
    else:
        raise ValueError(f"unsupported export format: {fmt!r}")
    return out


def ca_info(confdir: Path) -> dict:
    confdir = Path(confdir)
    if not ca_exists(confdir):
        raise CaNotFoundError(f"No CA at {confdir}")
    from mitmproxy import certs

    store = certs.CertStore.from_store(confdir, _BASENAME, _KEY_SIZE)
    ca = store.default_ca
    fp = ca.fingerprint()
    return {
        "confdir": str(confdir),
        "keycert": str(confdir / CA_KEYCERT),
        "cert_pem": str(confdir / CA_CERT_PEM),
        "cn": ca.cn,
        "serial": ca.serial,
        "fingerprint_sha256": fp.hex() if isinstance(fp, (bytes, bytearray)) else str(fp),
        "not_before": str(ca.notbefore),
        "not_after": str(ca.notafter),
    }
