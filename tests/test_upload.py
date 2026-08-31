"""Tests for the minimal, layout-preserving project upload.

Covers the ignore-file reader and rsync filter construction in
``ssh/rsync.py`` and the upload helper functions in ``tui/submit.py``
(Julia allowlist, extra-file relativisation, package-src warning).

asyncio.create_subprocess_exec is mocked throughout; no real rsync runs.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.jobs import validate
from clusterpilot.jobs.params_table import load_params_table
from clusterpilot.jobs.validate import Severity, SubmitIntent
from clusterpilot.ssh.rsync import (
    _build_filter_args,
    read_ignore_file,
    upload,
)
from clusterpilot.tui.submit import (
    _julia_upload_includes,
    _package_src_warning,
    _resolve_extra_file,
    _upload_includes,
    _validator_upload_paths,
)

# ── read_ignore_file ────────────────────────────────────────────────────────────

class TestReadIgnoreFile:
    def test_missing_returns_empty(self, tmp_path):
        assert read_ignore_file(tmp_path) == []

    def test_reads_canonical_name(self, tmp_path):
        (tmp_path / ".clusterpilotignore").write_text("data/\n*.h5\n")
        assert read_ignore_file(tmp_path) == ["data/", "*.h5"]

    def test_reads_legacy_name(self, tmp_path):
        (tmp_path / ".clusterpilot_ignore").write_text("output/\n")
        assert read_ignore_file(tmp_path) == ["output/"]

    def test_skips_comments_and_blanks(self, tmp_path):
        (tmp_path / ".clusterpilotignore").write_text(
            "# a comment\n\n  data/  \n  # indented comment\n*.png\n"
        )
        assert read_ignore_file(tmp_path) == ["data/", "*.png"]

    def test_merges_both_files_canonical_first_deduped(self, tmp_path):
        (tmp_path / ".clusterpilotignore").write_text("data/\nshared/\n")
        (tmp_path / ".clusterpilot_ignore").write_text("shared/\nlogs/\n")
        # shared/ appears in both; kept once, canonical ordering wins.
        assert read_ignore_file(tmp_path) == ["data/", "shared/", "logs/"]


# ── _build_filter_args ──────────────────────────────────────────────────────────

class TestBuildFilterArgs:
    def test_blocklist_only(self):
        args = _build_filter_args(["data/", "*.h5"], [])
        assert args == ["--exclude", "data/", "--exclude", "*.h5"]

    def test_empty(self):
        assert _build_filter_args([], []) == []

    def test_allowlist_orders_excludes_first_then_includes_then_catch_all(self):
        args = _build_filter_args(["data/"], ["Project.toml", "src/***"])
        assert args == [
            "--exclude", "data/",     # user excludes win
            "--include", "*/",        # descend into directories
            "--include", "Project.toml",
            "--include", "src/***",
            "--exclude", "*",         # drop everything else
        ]


# ── upload rsync invocation ─────────────────────────────────────────────────────

class _AsyncLines:
    def __init__(self, data):
        self._data = list(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._data:
            raise StopAsyncIteration
        return self._data.pop(0)


def _make_rsync_proc(returncode=0, lines=None):
    proc = MagicMock()
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.wait = AsyncMock(return_value=returncode)
    proc.stdout = _AsyncLines(lines or [])
    return proc


class TestUploadInvocation:
    async def test_upload_prunes_empty_dirs_and_passes_excludes(self):
        proc = _make_rsync_proc()
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ) as mock_exec:
            await upload(
                "host", "user", Path("/tmp/proj"), "/remote/job",
                excludes=["data/", "*.h5"],
            )
        args = [str(a) for a in mock_exec.call_args[0]]
        assert "--prune-empty-dirs" in args
        assert "--exclude" in args and "data/" in args and "*.h5" in args
        # No allowlist when includes is None: no catch-all "*" exclude.
        assert "*" not in args

    async def test_upload_allowlist_emits_include_rules(self):
        proc = _make_rsync_proc()
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ) as mock_exec:
            await upload(
                "host", "user", Path("/tmp/proj"), "/remote/job",
                excludes=["data/"],
                includes=["Project.toml", "src/***"],
            )
        args = [str(a) for a in mock_exec.call_args[0]]
        assert "--prune-empty-dirs" in args
        assert "*/" in args            # descend into dirs
        assert "Project.toml" in args
        assert "src/***" in args
        assert "*" in args             # catch-all exclude closes the allowlist


# ── _julia_upload_includes ──────────────────────────────────────────────────────

class TestJuliaUploadIncludes:
    def test_none_without_project_toml(self, tmp_path):
        assert _julia_upload_includes(tmp_path, "scripts/run.jl") is None

    def test_includes_manifest_src_and_driver(self, tmp_path):
        (tmp_path / "Project.toml").write_text('name = "X"\n')
        inc = _julia_upload_includes(tmp_path, "scripts/run.jl")
        assert inc == ["Project.toml", "Manifest.toml", "src/***", "scripts/run.jl"]

    def test_driver_inside_src_not_duplicated(self, tmp_path):
        (tmp_path / "Project.toml").write_text('name = "X"\n')
        inc = _julia_upload_includes(tmp_path, "src/main.jl")
        assert inc == ["Project.toml", "Manifest.toml", "src/***"]

    def test_no_driver(self, tmp_path):
        (tmp_path / "Project.toml").write_text('name = "X"\n')
        inc = _julia_upload_includes(tmp_path, "")
        assert inc == ["Project.toml", "Manifest.toml", "src/***"]


# ── _resolve_extra_file ─────────────────────────────────────────────────────────

class TestResolveExtraFile:
    def test_relative_entry(self, tmp_path):
        local, rel, warning = _resolve_extra_file("scripts/util.jl", tmp_path)
        assert local == tmp_path / "scripts/util.jl"
        assert rel == Path("scripts/util.jl")
        assert warning is None

    def test_absolute_inside_project_relativised(self, tmp_path):
        target = tmp_path / "scripts" / "util.jl"
        target.parent.mkdir(parents=True)
        target.write_text("x")
        local, rel, warning = _resolve_extra_file(str(target), tmp_path)
        assert local == target.resolve()
        assert rel == Path("scripts/util.jl")
        assert warning is None

    def test_absolute_outside_project_lands_at_basename_with_warning(self, tmp_path):
        outside = tmp_path.parent / "elsewhere" / "ladder.txt"
        outside.parent.mkdir(parents=True)
        outside.write_text("x")
        local, rel, warning = _resolve_extra_file(str(outside), tmp_path)
        assert local == outside.resolve()
        assert rel == Path("ladder.txt")        # basename only, no home/... tree
        assert warning is not None and "outside PROJECT DIR" in warning


# ── _package_src_warning ────────────────────────────────────────────────────────

class TestPackageSrcWarning:
    def test_no_warning_for_project_root(self, tmp_path):
        (tmp_path / "Project.toml").write_text('name = "X"\n')
        assert _package_src_warning(tmp_path) is None

    def test_warns_for_package_src_matching_name(self, tmp_path):
        (tmp_path / "Project.toml").write_text('name = "SpinGlassLab"\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "SpinGlassLab.jl").write_text("module SpinGlassLab end")
        assert _package_src_warning(src) is not None

    def test_warns_for_dir_named_src_under_a_project(self, tmp_path):
        (tmp_path / "Project.toml").write_text('name = "Y"\n')
        src = tmp_path / "src"
        src.mkdir()
        assert _package_src_warning(src) is not None

    def test_no_warning_when_parent_has_no_project_toml(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        assert _package_src_warning(sub) is None


# ── the upload set handed to the validator (#52) ────────────────────────────────

DRIVER = "scripts/drivers/run_zfc_ewald.jl"

SCRIPT = f"""#!/bin/bash
#SBATCH --job-name=zfc
#SBATCH --array=0-69

julia --project=. {DRIVER}
"""


def julia_project(tmp_path: Path, *, with_driver: bool = True) -> Path:
    """A Julia project laid out the way SpinGlassLab is."""
    (tmp_path / "Project.toml").write_text('name = "SpinGlassLab"\n')
    (tmp_path / "Manifest.toml").write_text("\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "SpinGlassLab.jl").write_text("module SpinGlassLab\nend\n")
    if with_driver:
        (tmp_path / "scripts" / "drivers").mkdir(parents=True)
        (tmp_path / DRIVER).write_text("println(1)\n")
    return tmp_path


def findings_for(project_dir: Path, extra_files, table=None):
    """Run the driver-uploaded check the way the submit screen now does."""
    intent = SubmitIntent(
        driver_rel=DRIVER,
        upload_paths=_validator_upload_paths(
            str(project_dir), DRIVER, extra_files, table
        ),
    )
    return validate._check_driver_uploaded(SCRIPT, intent)


class TestValidatorUploadPaths:
    def test_empty_extra_files_and_the_driver_present_is_clean(self, tmp_path):
        """(a) The case that used to skip the check entirely."""
        project = julia_project(tmp_path)
        assert findings_for(project, []) == []

    def test_extra_files_naming_something_else_is_clean(self, tmp_path):
        """(b) The case that blocked a correct 70-task array on Narval."""
        project = julia_project(tmp_path)
        (project / "experiments").mkdir()
        (project / "experiments" / "sweep.tsv").write_text("x\n1\n")
        findings = findings_for(project, ["experiments/sweep.tsv"])
        assert findings == [], [f.message for f in findings]

    def test_a_driver_that_is_not_on_disk_blocks(self, tmp_path):
        """(c) Nothing to upload, so the job would die on its first line."""
        project = julia_project(tmp_path, with_driver=False)
        findings = findings_for(project, [])
        assert len(findings) == 1
        assert findings[0].check == "driver-not-uploaded"
        assert findings[0].severity is Severity.BLOCKING

    def test_the_driver_is_in_the_set(self, tmp_path):
        project = julia_project(tmp_path)
        assert DRIVER in _validator_upload_paths(str(project), DRIVER, [], None)

    def test_extra_files_are_in_the_set(self, tmp_path):
        project = julia_project(tmp_path)
        (project / "data.jld2").write_text("x")
        paths = _validator_upload_paths(str(project), DRIVER, ["data.jld2"], None)
        assert "data.jld2" in paths

    def test_an_extra_file_that_does_not_exist_is_not_in_the_set(self, tmp_path):
        project = julia_project(tmp_path)
        paths = _validator_upload_paths(str(project), DRIVER, ["ghost.jld2"], None)
        assert "ghost.jld2" not in paths

    def test_the_parameter_table_travels_under_its_own_name(self, tmp_path):
        project = julia_project(tmp_path)
        table_file = project / "experiments" / "sweep.tsv"
        table_file.parent.mkdir()
        table_file.write_text("a\tb\n1\t2\n")
        table = load_params_table(table_file)
        paths = _validator_upload_paths(str(project), DRIVER, [], table)
        assert "sweep.tsv" in paths

    def test_a_whole_tree_upload_reports_an_unknown_set(self, tmp_path):
        """No Project.toml means a blocklist rsync, which covers everything."""
        (tmp_path / "run.py").write_text("print(1)\n")
        assert _validator_upload_paths(str(tmp_path), "run.py", [], None) == ()

    def test_single_file_mode_reports_an_unknown_set(self, tmp_path):
        assert _validator_upload_paths("", DRIVER, [], None) == ()

    def test_rsync_patterns_survive_the_existence_filter(self, tmp_path):
        project = julia_project(tmp_path)
        assert "src/***" in _validator_upload_paths(str(project), DRIVER, [], None)


class TestUploadIncludes:
    def test_included_files_that_exist_are_added(self, tmp_path):
        project = julia_project(tmp_path)
        (project / "helpers.jl").write_text("x")
        includes, missing = _upload_includes(project, DRIVER, ["helpers.jl"])
        assert "helpers.jl" in includes
        assert missing == []

    def test_included_files_that_do_not_exist_are_reported(self, tmp_path):
        project = julia_project(tmp_path)
        includes, missing = _upload_includes(project, DRIVER, ["ghost.jl"])
        assert "ghost.jl" not in includes
        assert missing == ["ghost.jl"]

    def test_a_non_julia_project_has_no_allowlist(self, tmp_path):
        includes, missing = _upload_includes(tmp_path, "run.py", [])
        assert includes is None
        assert missing == []
