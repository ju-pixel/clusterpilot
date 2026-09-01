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


class TestResultsRowInTheDetailPane:
    """Issues #15 and #16: nothing in the TUI said where results land."""

    def _job(self, local_dir: str):
        from clusterpilot.db import JobRecord
        return JobRecord(
            job_id="4137812", job_name="ising-sweep", cluster_name="narval",
            host="h", user="u", account="a", partition="p", script_path="s",
            working_dir="w", local_dir=local_dir, walltime="01:00:00",
            status="COMPLETED",
        )

    def test_the_detail_pane_shows_the_results_directory(self):
        from clusterpilot.tui.jobs import _format_meta
        meta = _format_meta(self._job("/data/runs/clusterpilot_jobs/ising-sweep"))
        assert "RESULTS" in meta
        assert "/data/runs/clusterpilot_jobs/ising-sweep" in meta

    def test_a_home_path_is_shown_with_a_tilde(self):
        from pathlib import Path

        from clusterpilot.tui.jobs import _format_meta
        local = str(Path.home() / "clusterpilot_jobs" / "ising-sweep")
        meta = _format_meta(self._job(local))
        assert "~/clusterpilot_jobs/ising-sweep" in meta
        assert str(Path.home()) not in meta

    def test_the_rsync_hint_names_the_results_directory(self):
        from clusterpilot.tui.app import HINTS
        assert "RESULTS" in HINTS["btn-rsync"]


class TestEfficiencyRow:
    """Issue #31: the seff figure has somewhere to be read in F1."""

    def _job(self, efficiency: str):
        from clusterpilot.db import JobRecord
        return JobRecord(
            job_id="4137812", job_name="ising-sweep", cluster_name="narval",
            host="h", user="u", account="a", partition="p", script_path="s",
            working_dir="w", local_dir="/data/runs", walltime="01:00:00",
            status="COMPLETED", efficiency=efficiency,
        )

    def test_shown_when_seff_answered(self):
        from clusterpilot.tui.jobs import _format_meta
        meta = _format_meta(self._job("CPU 12%, mem 6% of 16 GB"))
        assert "EFFICIENCY" in meta
        assert "CPU 12%, mem 6% of 16 GB" in meta

    def test_absent_while_there_is_nothing_to_show(self):
        from clusterpilot.tui.jobs import _format_meta
        assert "EFFICIENCY" not in _format_meta(self._job(""))


class TestQueueRowsCarryTheArrayBreakdown:
    """Julia's request: reading four arrays across four clusters should not
    mean opening each one, which is what still sends her to ssh."""

    def _job(self, **kwargs):
        from clusterpilot.db import JobRecord
        defaults = dict(
            job_id="20014027", job_name="zfc-field-cubic", cluster_name="rorqual",
            host="h", user="u", account="a", partition="p", script_path="s",
            working_dir="w", local_dir="l", walltime="24:00:00",
            status="RUNNING", status_detail="66R/4PD",
        )
        defaults.update(kwargs)
        return JobRecord(**defaults)

    def test_the_row_shows_the_breakdown(self):
        from clusterpilot.tui.jobs import _format_list_item
        row = _format_list_item(self._job())
        assert "66R/4PD" in row
        assert "zfc-field-cubic" in row

    def test_a_plain_job_gains_nothing(self):
        """summary is empty for a single-task job, so rows stay as they were."""
        from clusterpilot.tui.jobs import _format_list_item
        row = _format_list_item(self._job(status_detail=""))
        assert "#20014027" in row
        assert row.rstrip().endswith("[/]")

    def test_no_line_outgrows_the_queue_panel(self):
        """34 columns less two border columns. Anything wider is clipped, and
        the clipped end is the right-hand one, where the breakdown sits."""
        import re
        from clusterpilot.tui.jobs import _ROW_WIDTH, _format_list_item
        row = _format_list_item(self._job(
            job_id="20950180", job_name="zfc-field-sweep-rcp-longname",
            cluster_name="trillium-gpu", status_detail="120R/880PD",
        ))
        for line in row.split("\n"):
            visible = re.sub(r"\[/?[^\]]*\]", "", line)
            assert len(visible) <= _ROW_WIDTH, repr(visible)

    def test_the_breakdown_survives_a_long_name(self):
        """The name gives way, not the number that was added."""
        from clusterpilot.tui.jobs import _format_list_item
        row = _format_list_item(self._job(
            job_name="zfc-field-sweep-rcp-longname", status_detail="120R/880PD",
        ))
        assert "120R/880PD" in row

    def test_the_title_totals_across_clusters(self):
        from clusterpilot.tui.jobs import _queue_title
        title = _queue_title([
            self._job(job_id="1", cluster_name="rorqual", status_detail="66R/4PD"),
            self._job(job_id="2", cluster_name="narval", status_detail="12R/98PD"),
            self._job(job_id="3", cluster_name="grex", status_detail="24R/76PD"),
        ])
        assert "102R" in title      # 66 + 12 + 24
        assert "178PD" in title     # 4 + 98 + 76

    def test_the_header_reads_the_same_way_round_as_the_rows(self):
        """First cut sorted abbreviations and produced "287PD/103R" over rows
        that all read "12R/98PD". Both now format through slurm.format_summary."""
        from clusterpilot.tui.jobs import _queue_title
        title = _queue_title([
            self._job(job_id="1", status_detail="12R/98PD"),
            self._job(job_id="2", status_detail="24R/76PD"),
        ])
        assert title.index("36R") < title.index("174PD")

    def test_finished_jobs_do_not_swamp_the_total(self):
        """Otherwise a month of completions buries the live numbers."""
        from clusterpilot.tui.jobs import _queue_title
        title = _queue_title([
            self._job(job_id="1", status="RUNNING", status_detail="10R/60PD"),
            self._job(job_id="2", status="COMPLETED", status_detail="500C"),
        ])
        assert "10R" in title
        assert "60PD" in title
        assert "500C" not in title

    def test_a_queue_with_no_arrays_keeps_the_plain_title(self):
        from clusterpilot.tui.jobs import _queue_title
        assert _queue_title([]) == "═ QUEUE "
        assert _queue_title([self._job(status_detail="")]) == "═ QUEUE "
