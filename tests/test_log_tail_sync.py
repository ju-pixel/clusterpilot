"""The log tail that reaches the dashboard must be a log, not an excerpt (#64).

Every sync path used to ask `tail_log` for its default 50 lines, so an
individual job's Logs tab could never show more than 50 lines however well it
scrolled. These pin both halves of the fix: the daemon asks for a log's worth
of lines, and what it pushes is clipped to a byte budget from the front, so a
job that emits very long lines cannot turn one status transition into a huge
payload.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from clusterpilot.config import ClusterProfile, Config, Defaults
from clusterpilot.db import JobRecord
from clusterpilot.jobs.daemon import (
    SYNC_TAIL_BYTES,
    SYNC_TAIL_LINES,
    TRIM_MARKER,
    PollDaemon,
)

_PROFILE = ClusterProfile(name="grex", host="grex.hpc.umanitoba.ca", user="juliaf",
                          account="def-stamps", scratch="$HOME/jobs")


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="12345",
        job_name="bench_run",
        cluster_name="grex",
        host="grex.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path="/local/bench/job.sh",
        working_dir="/home/juliaf/jobs/bench_run",
        local_dir="/local/bench",
        walltime="14:00:00",
        log_path="/home/juliaf/jobs/bench_run/bench-12345.out",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _make_daemon() -> PollDaemon:
    return PollDaemon(Config(defaults=Defaults()), db_path=":memory:")


class TestClipTail:
    def test_a_tail_inside_the_budget_is_untouched(self):
        from clusterpilot.jobs.daemon import clip_tail

        text = "\n".join(f"line {i}" for i in range(100))
        assert clip_tail(text) == text

    def test_an_oversized_tail_is_clipped_from_the_front(self):
        from clusterpilot.jobs.daemon import clip_tail

        text = "\n".join(f"line {i}" for i in range(20_000))
        clipped = clip_tail(text)

        assert len(clipped.encode("utf-8")) <= SYNC_TAIL_BYTES
        # The end of a log is the part worth reading, so it survives and the
        # beginning is what goes.
        assert clipped.endswith("line 19999")
        assert "line 0\n" not in clipped
        # A reader must be able to tell a truncated log from a short one.
        assert clipped.splitlines()[0] == TRIM_MARKER

    def test_one_line_longer_than_the_whole_budget_keeps_its_tail(self):
        from clusterpilot.jobs.daemon import clip_tail

        clipped = clip_tail("x" * 10 + "y" * SYNC_TAIL_BYTES * 2)

        assert len(clipped.encode("utf-8")) <= SYNC_TAIL_BYTES
        # Returning the marker and nothing else would be worse than useless.
        assert clipped.splitlines()[0] == TRIM_MARKER
        assert clipped.endswith("y")

    def test_multibyte_characters_are_not_split_into_mojibake(self):
        from clusterpilot.jobs.daemon import clip_tail

        clipped = clip_tail("✓ done\n" * 20_000)

        assert len(clipped.encode("utf-8")) <= SYNC_TAIL_BYTES
        assert clipped.endswith("✓ done")


class TestWhatTheDaemonAsksFor:
    def test_the_synced_tail_is_a_log_not_a_notification_excerpt(self):
        # 50 was `tail_log`'s default and the reason the dashboard could not
        # show a full log even once it scrolled.
        assert SYNC_TAIL_LINES > 50

    async def test_tail_for_sync_asks_for_the_full_count(self):
        daemon = _make_daemon()
        job = _make_job()
        with patch("clusterpilot.jobs.daemon.tail_log",
                   new=AsyncMock(return_value="out")) as tail:
            await daemon._tail_for_sync(_PROFILE, job, "RUNNING")

        assert tail.await_args.kwargs["n_lines"] == SYNC_TAIL_LINES

    async def test_failure_excerpt_asks_for_the_full_count(self):
        daemon = _make_daemon()
        job = _make_job()
        with patch("clusterpilot.jobs.daemon.find_array_logs",
                   new=AsyncMock(return_value={})), \
                patch("clusterpilot.jobs.daemon.tail_log",
                      new=AsyncMock(return_value="boom")) as tail:
            assert await daemon._failure_excerpt(_PROFILE, job) == "boom"

        assert tail.await_args.kwargs["n_lines"] == SYNC_TAIL_LINES


class TestWhatTheDaemonPushes:
    async def test_sync_clips_before_pushing(self):
        daemon = _make_daemon()
        job = _make_job()
        huge = "\n".join(f"line {i}" for i in range(20_000))
        with patch("clusterpilot.jobs.daemon.sync_job",
                   new=AsyncMock(return_value=True)) as sync_job:
            await daemon._sync(job, "FAILED", log_tail=huge)

        pushed = sync_job.await_args.kwargs["log_tail"]
        assert len(pushed.encode("utf-8")) <= SYNC_TAIL_BYTES
        assert pushed.endswith("line 19999")

    async def test_a_short_tail_is_pushed_verbatim(self):
        daemon = _make_daemon()
        job = _make_job()
        with patch("clusterpilot.jobs.daemon.sync_job",
                   new=AsyncMock(return_value=True)) as sync_job:
            await daemon._sync(job, "FAILED", log_tail="all fine\n")

        assert sync_job.await_args.kwargs["log_tail"] == "all fine\n"

    async def test_no_tail_stays_none(self):
        daemon = _make_daemon()
        job = _make_job()
        with patch("clusterpilot.jobs.daemon.sync_job",
                   new=AsyncMock(return_value=True)) as sync_job:
            await daemon._sync(job, "RUNNING")

        assert sync_job.await_args.kwargs["log_tail"] is None
