"""Path resolution on the F2 Submit screen.

Regression test for #35: a relative PARAM TABLE path was joined onto a
``project_dir`` name that was never bound in ``_stream_script``, so entering
``params.tsv`` raised NameError instead of loading the table.
"""
from __future__ import annotations

from pathlib import Path

from clusterpilot.tui.submit import _resolve_table_path


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
