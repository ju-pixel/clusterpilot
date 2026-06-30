"""Tests for the generated-script display formatter in ``tui/submit.py``.

``_format_script`` wraps each line in Rich colour markup. The regression these
tests guard: literal square brackets in the script (bash array indices, globs,
regex classes) must survive rendering rather than being parsed as Rich markup
and dropped.
"""
from __future__ import annotations

import io

from rich.console import Console

from clusterpilot.tui.submit import _format_script


def _render(markup: str) -> str:
    """Render Rich markup to plain text the way the TUI panel would."""
    buf = io.StringIO()
    Console(file=buf, force_terminal=False, width=200).print(
        markup, markup=True, highlight=False
    )
    return buf.getvalue()


class TestFormatScriptBrackets:
    def test_bash_array_index_preserved(self):
        line = "SELECTED_ETA=${ETA_VALUES[$SLURM_ARRAY_TASK_ID]}"
        assert "[$SLURM_ARRAY_TASK_ID]" in _render(_format_script(line))

    def test_regex_class_preserved(self):
        line = "grep -E '[0-9]+' results.txt"
        assert "[0-9]+" in _render(_format_script(line))

    def test_glob_class_preserved(self):
        line = "rm -f output_[abc].dat"
        assert "output_[abc].dat" in _render(_format_script(line))

    def test_literal_markup_not_interpreted(self):
        # A line that happens to contain a real Rich tag must show verbatim.
        line = "echo '[bold]not a style[/]'"
        rendered = _render(_format_script(line))
        assert "[bold]not a style[/]" in rendered


class TestFormatScriptColouring:
    def test_sbatch_line_keeps_text(self):
        rendered = _render(_format_script("#SBATCH --array=0-9"))
        assert "#SBATCH --array=0-9" in rendered

    def test_blank_line_stays_blank(self):
        # Two lines with a blank between them: the blank must not gain markup.
        out = _format_script("module load julia\n\njulia run.jl")
        assert out.splitlines()[1] == ""
