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
