"""The jobs pane must agree with the daemon about which states are terminal.

Regression test for issue #3: the TUI hardcoded four terminal states, so an
OUT_OF_MEMORY or NODE_FAIL job kept KILL enabled, never enabled CLEAN or
RSYNC, and rendered with the unknown-status glyph.
"""
from __future__ import annotations

import pytest

from clusterpilot.cluster.slurm import TERMINAL_STATES
from clusterpilot.tui.jobs import _STATUS_STYLE, _status_rich


class TestTerminalStatesInTui:
    @pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
    def test_every_terminal_state_has_a_glyph(self, state: str):
        assert state in _STATUS_STYLE
        assert "?" not in _status_rich(state)

    def test_oom_and_node_fail_render_as_failures(self):
        for state in ("OUT_OF_MEMORY", "NODE_FAIL"):
            colour, icon = _STATUS_STYLE[state]
            assert (colour, icon) == _STATUS_STYLE["FAILED"]

    def test_unknown_state_still_gets_the_fallback_glyph(self):
        assert "?" in _status_rich("SUSPENDED")


class TestQueueRowShowsTheFullJobId:
    def test_full_id_not_a_suffix(self):
        from clusterpilot.db import JobRecord
        from clusterpilot.tui.jobs import _format_list_item
        job = JobRecord(
            job_id="4137812", job_name="ising-sweep", cluster_name="narval",
            host="h", user="u", account="a", partition="p", script_path="s",
            working_dir="w", local_dir="l", walltime="01:00:00", status="RUNNING",
        )
        row = _format_list_item(job)
        # The detail header prints the full id; the queue must match it, not
        # show a six-digit suffix that reads as a different job.
        assert "#4137812" in row
        assert "#137812 " not in row
