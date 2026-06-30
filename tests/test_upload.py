"""Tests for the minimal, layout-preserving project upload.

Covers the ignore-file reader and rsync filter construction in
``ssh/rsync.py`` and the upload helper functions in ``tui/submit.py``
(Julia allowlist, extra-file relativisation, package-src warning).

asyncio.create_subprocess_exec is mocked throughout; no real rsync runs.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.ssh.rsync import (
    _build_filter_args,
    read_ignore_file,
    upload,
)
from clusterpilot.tui.submit import (
    _julia_upload_includes,
    _package_src_warning,
    _resolve_extra_file,
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
