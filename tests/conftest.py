"""Suite-wide guards.

The submit flow writes each job's local results under PROJECT DIR when it is
set and under the real home directory otherwise. A test that drives a
submission with PROJECT DIR blank therefore lands a directory in the
developer's actual ``~/clusterpilot_jobs``, which is what happened for
several weeks before #77. This fixture sends that fallback to the test's
temporary directory so no test can reach the real one, whatever it forgets
to set. Tests that examine the helper itself import it by name, so they keep
seeing the unpatched function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import clusterpilot.tui.submit as submit_module


@pytest.fixture(autouse=True)
def _results_root_stays_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = submit_module._local_results_root

    def guarded(project_dir_str: str) -> Path:
        if project_dir_str:
            return real(project_dir_str)
        return tmp_path / "clusterpilot_jobs"

    monkeypatch.setattr(submit_module, "_local_results_root", guarded)
