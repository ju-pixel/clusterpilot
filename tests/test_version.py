"""The version must agree in every place that states it.

Release step 1 checks this by eye. A drift between pyproject.toml and
__init__.py means the built artefact and the installed package disagree about
what they are, which is only noticed after upload.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import clusterpilot

_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    with open(_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_pyproject_and_package_agree():
    assert clusterpilot.__version__ == _pyproject_version()


def test_the_cli_reports_the_same_version():
    out = subprocess.run(
        [sys.executable, "-m", "clusterpilot", "--version"],
        capture_output=True, text=True, cwd=_ROOT,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"clusterpilot {clusterpilot.__version__}"


def test_the_changelog_has_a_section_for_this_version():
    changelog = (_ROOT / "CHANGELOG.md").read_text()
    assert f"## v{clusterpilot.__version__} (" in changelog
