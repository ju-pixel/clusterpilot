"""Path resolution on the F2 Submit screen.

Regression test for #35: a relative PARAM TABLE path was joined onto a
``project_dir`` name that was never bound in ``_stream_script``, so entering
``params.tsv`` raised NameError instead of loading the table.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import clusterpilot.tui.submit as submit_module
from clusterpilot.tui.submit import (
    SubmitError,
    _local_results_root,
    _mkdir_command,
    _normalise_driver_rel,
    _resolve_table_path,
    _strip_job_name_suffix,
)


class TestResolveTablePath:
    def test_relative_path_resolves_against_the_project_dir(self):
        assert _resolve_table_path("/home/tester/project", "params.tsv") == Path(
            "/home/tester/project/params.tsv"
        )

    def test_nested_relative_path_keeps_its_layout(self):
        assert _resolve_table_path("/home/tester/project", "data/params.csv") == Path(
            "/home/tester/project/data/params.csv"
        )

    def test_absolute_path_is_left_alone(self):
        assert _resolve_table_path("/home/tester/project", "/data/params.tsv") == Path(
            "/data/params.tsv"
        )

    def test_relative_path_without_a_project_dir_stays_relative(self):
        assert _resolve_table_path("", "params.tsv") == Path("params.tsv")

    def test_tilde_is_expanded(self):
        assert _resolve_table_path("", "~/params.tsv") == Path.home() / "params.tsv"

    def test_project_dir_tilde_is_expanded(self):
        assert (
            _resolve_table_path("~/project", "params.tsv")
            == Path.home() / "project" / "params.tsv"
        )


# ── Blank Select sentinel (#42, root cause of #11) ───────────────────────────

class TestBlankSelectSentinel:
    """On Textual 8 the empty-Select sentinel is ``Select.NULL``.

    ``Select.BLANK`` no longer exists on ``Select``; the name resolves to
    ``Widget.BLANK`` (``False``), so ``value is not Select.BLANK`` was always
    true and a blank partition picker sent the literal ``Select.NULL`` into
    the generated script as ``--partition=Select.NULL``.
    """

    def test_blank_select_value_is_the_null_sentinel(self):
        from textual.widgets import Select
        select = Select(options=[("a", "a")], allow_blank=True)
        assert select.value is Select.NULL
        assert select.value is not getattr(Select, "BLANK", object())

    def test_submit_view_never_compares_against_select_blank(self):
        from pathlib import Path
        import clusterpilot.tui.submit as submit
        source = Path(submit.__file__).read_text()
        code_lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("Select.BLANK" in ln for ln in code_lines)


# ── Job-name suffix stacking (#14) ────────────────────────────────────────────

class TestStripJobNameSuffix:
    """Issue #14: a re-submit appended a second "-MMDD-HHMM" to the first."""

    def test_strips_a_clusterpilot_timestamp_suffix(self):
        assert _strip_job_name_suffix("bench_run-0827-1431") == "bench_run"

    def test_leaves_a_plain_name_alone(self):
        assert _strip_job_name_suffix("bench_run") == "bench_run"

    def test_is_idempotent_so_suffixes_cannot_stack(self):
        once = _strip_job_name_suffix("bench_run-0827-1431")
        assert _strip_job_name_suffix(f"{once}-0828-0902") == "bench_run"

    def test_leaves_a_name_that_merely_ends_in_digits(self):
        assert _strip_job_name_suffix("sweep_2026") == "sweep_2026"

    def test_only_strips_the_trailing_suffix(self):
        assert _strip_job_name_suffix("run-0827-1431-final") == "run-0827-1431-final"


# ── Local results root (#15, #16) ─────────────────────────────────────────────

class TestLocalResultsRoot:
    """Issues #15 and #16: results followed the launch directory."""

    def test_project_dir_holds_the_results(self):
        assert _local_results_root("/home/tester/project") == Path(
            "/home/tester/project/clusterpilot_jobs"
        )

    def test_tilde_in_the_project_dir_is_expanded(self):
        assert (
            _local_results_root("~/project")
            == Path.home() / "project" / "clusterpilot_jobs"
        )

    def test_without_a_project_dir_results_go_under_home(self):
        assert _local_results_root("") == Path.home() / "clusterpilot_jobs"

    def test_never_the_working_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _local_results_root("") != tmp_path / "clusterpilot_jobs"

    def test_submit_never_roots_results_at_cwd(self):
        import clusterpilot.tui.submit as submit
        source = Path(submit.__file__).read_text()
        assert 'Path.cwd() / "clusterpilot_jobs"' not in source


# ── Driver script normalisation (#6) ──────────────────────────────────────────

class TestNormaliseDriverRel:
    """Issue #6: absolute and "./" driver paths matched no rsync pattern."""

    def test_a_relative_path_is_unchanged(self):
        assert _normalise_driver_rel(Path("/home/tester/project"), "scripts/run.jl") == (
            "scripts/run.jl"
        )

    def test_a_dot_slash_prefix_is_dropped(self):
        assert _normalise_driver_rel(Path("/home/tester/project"), "./run.jl") == "run.jl"

    def test_surrounding_whitespace_is_ignored(self):
        assert _normalise_driver_rel(Path("/home/tester/project"), "  run.jl  ") == "run.jl"

    def test_an_absolute_path_inside_the_project_becomes_relative(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        driver = tmp_path / "scripts" / "run.jl"
        driver.write_text("1")
        assert _normalise_driver_rel(tmp_path, str(driver)) == "scripts/run.jl"

    def test_an_absolute_path_outside_the_project_is_refused(self, tmp_path):
        outside = tmp_path.parent / "elsewhere" / "run.jl"
        with pytest.raises(SubmitError):
            _normalise_driver_rel(tmp_path / "project", str(outside))

    def test_an_empty_field_stays_empty(self):
        assert _normalise_driver_rel(Path("/home/tester/project"), "") == ""


# ── Batched mkdir for extra files (#13) ───────────────────────────────────────

class TestMkdirCommand:
    """Issue #13: one mkdir round trip per extra file timed out on a busy node."""

    def test_every_directory_lands_in_one_command(self):
        cmd = _mkdir_command(["/jobs/run/data", "/jobs/run/conf"])
        assert cmd.startswith("mkdir -p ")
        assert cmd.count("mkdir") == 1
        assert "/jobs/run/data" in cmd and "/jobs/run/conf" in cmd

    def test_duplicates_collapse(self):
        cmd = _mkdir_command(["/jobs/run", "/jobs/run", "/jobs/run"])
        assert cmd == "mkdir -p /jobs/run"

    def test_no_directories_means_no_command(self):
        assert _mkdir_command([]) == ""
        assert _mkdir_command(["", ""]) == ""

    def test_submit_batches_the_mkdir_with_a_long_timeout(self):
        import clusterpilot.tui.submit as submit
        source = Path(submit.__file__).read_text()
        assert "_mkdir_command(d for _, d in planned)" in source
        assert "timeout=120.0" in source


# ── Truncated generation is never submittable (#20) ───────────────────────────

class TestTruncatedGenerationIsRefused:
    """Issue #20: a generation cut at the token ceiling must not reach sbatch."""

    def test_the_message_names_the_parameter_table_remedy(self):
        message = submit_module._TRUNCATED_MESSAGE.lower()
        assert "script body" in message
        assert "parameter table" in message
        assert "cannot be submitted" in message

    def test_the_guard_disables_submit(self):
        source = Path(submit_module.__file__).read_text()
        guard = source.split("if self._last_usage.truncated:", 1)[1]
        guard = guard.split("# Check the generated script", 1)[0]
        assert "_TRUNCATED_MESSAGE" in guard
        assert '#btn-submit", Button).disabled = True' in guard
        assert "return" in guard
