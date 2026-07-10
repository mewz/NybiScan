"""Create a project, close it, reopen it; metadata round-trips."""

from __future__ import annotations

from nybiscan.core import project as core_project


def test_create_close_reopen(tmp_path):
    bundle = tmp_path / "demo.nybiscan"

    proj = core_project.create_project(bundle, name="Demo", scope=["example.com"])
    meta = proj.meta()
    assert meta.name == "Demo"
    assert meta.encrypted is False
    uuid = meta.uuid
    proj.close()

    # On-disk bundle is well formed.
    assert (bundle / "session.db").exists()
    assert (bundle / "project.toml").exists()
    assert (bundle / "bodies").is_dir()
    assert (bundle / "ca").is_dir()

    reopened = core_project.open_project(bundle)
    meta2 = reopened.meta()
    assert meta2.uuid == uuid
    assert meta2.name == "Demo"
    reopened.close()


def test_normalizes_suffix(tmp_path):
    # Path without the .nybiscan suffix is normalized.
    proj = core_project.create_project(tmp_path / "noSuffix", name="X")
    assert proj.bundle.name == "noSuffix.nybiscan"
    proj.close()
