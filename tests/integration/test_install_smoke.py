"""Install smoke test: validate clean install and entrypoint.

Per Q11: Pytest test that spawns subprocess to verify pip install -e .
and avos --version work. Ensures packaging and entrypoint are correct.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_avos_entrypoint_available() -> None:
    """avos --version runs and returns version string."""
    result = subprocess.run(
        ["avos", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"avos --version failed: {result.stderr}"
    out = (result.stdout + result.stderr).strip()
    assert "avos" in out.lower(), f"Expected 'avos' in output: {out}"
    # Version format: avos X.Y.Z
    match = re.search(r"avos\s+(\d+\.\d+\.\d+)", out, re.IGNORECASE)
    assert match, f"Expected version pattern 'avos X.Y.Z' in: {out}"


def test_pip_install_and_avos_version() -> None:
    """pip install -e . succeeds and avos --version works."""
    install = subprocess.run(
        ["python", "-m", "pip", "install", "-e", ".", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert install.returncode == 0, f"pip install failed: {install.stderr}"

    version = subprocess.run(
        ["avos", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert version.returncode == 0
    assert "avos" in (version.stdout + version.stderr).lower()
