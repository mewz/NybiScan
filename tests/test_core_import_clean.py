"""The core must be importable with zero GUI/API framework dependencies."""

from __future__ import annotations

import subprocess
import sys


def test_core_imports_without_fastapi():
    # Run in a fresh interpreter so nothing else has imported fastapi first.
    code = (
        "import importlib, sys;"
        "importlib.import_module('nybiscan.core');"
        "importlib.import_module('nybiscan.core.project');"
        "assert 'fastapi' not in sys.modules, 'core pulled in fastapi';"
        "assert 'uvicorn' not in sys.modules, 'core pulled in uvicorn';"
        "print('core import clean')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "core import clean" in result.stdout
