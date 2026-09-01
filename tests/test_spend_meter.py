"""The spend meter must be able to be trusted (#66, #67).

It was wrong in three ways at once, all of them downward: the running total
priced a whole history at the configured default model's rate, it summed the
jobs table so every regeneration and abandoned draft was invisible, and an
unpriced model borrowed Sonnet 4.6's rate at two of the three call sites.

These pin the arithmetic and the counting. The hosted allowance gets retuned
from whatever this reports (#70), so a figure that reads low is not a cosmetic
problem.
"""
from __future__ import annotations

from pathlib import Path

import aiosqlite

from clusterpilot.db import (
    JobRecord,
    get_spend_by_model,
    init_db,
    insert_job,
    record_generation,
)
from clusterpilot.jobs.ai_gen import estimate_cost


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
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _total(rows: list[tuple[str, int, int]]) -> float:
    """Price each model at its own rate, the way the title bar does."""
    return sum(
        cost
        for model, inp, out in rows
        if (cost := estimate_cost(model, inp, out)) is not None
    )


class TestPricedPerModel:
    async def test_a_mixed_history_is_not_priced_at_one_rate(self, tmp_path: Path):
        """The bug: one Opus generation displayed at the Sonnet rate, 2.5x under."""
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            await record_generation(
                db, model="claude-sonnet-5",
                input_tokens=1_000_000, output_tokens=1_000_000,
            )
            await record_generation(
                db, model="claude-opus-5",
                input_tokens=1_000_000, output_tokens=1_000_000,
            )
            rows = await get_spend_by_model(db)

        # Sonnet 5 is $2 + $10, Opus 5 is $5 + $25.
        assert _total(rows) == 42.00
        # Priced at the Sonnet default across the board, as before, this would
        # have read 24.00.
        assert _total(rows) != 24.00

    async def test_generations_of_one_model_are_summed_together(self, tmp_path: Path):
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            for _ in range(3):
                await record_generation(
                    db, model="claude-sonnet-5",
                    input_tokens=1_000_000, output_tokens=0,
                )
            rows = await get_spend_by_model(db)

        assert rows == [("claude-sonnet-5", 3_000_000, 0)]
        assert _total(rows) == 6.00

    async def test_an_unpriced_model_contributes_nothing_and_is_visible(
        self, tmp_path: Path,
    ):
        """A local model cannot be added up, so it must not be guessed at."""
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            await record_generation(
                db, model="llama3.2", input_tokens=500_000, output_tokens=500_000,
            )
            await record_generation(
                db, model="claude-sonnet-5",
                input_tokens=1_000_000, output_tokens=0,
            )
            rows = await get_spend_by_model(db)

        assert _total(rows) == 2.00
        # Still on the books, so the title bar can mark the total as a floor
        # rather than silently dropping it.
        assert ("llama3.2", 500_000, 500_000) in rows
        assert estimate_cost("llama3.2", 500_000, 500_000) is None


class TestEveryBilledCallIsCounted:
    async def test_a_regenerated_script_counts_both_calls(self, tmp_path: Path):
        """The old total kept only the last generation of a submitted job."""
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            # Two goes at the same script, then the second one is submitted.
            for _ in range(2):
                await record_generation(
                    db, model="claude-opus-5",
                    input_tokens=1_000_000, output_tokens=0,
                )
            await insert_job(db, _make_job(
                input_tokens=1_000_000, output_tokens=0,
                model_used="claude-opus-5",
            ))
            rows = await get_spend_by_model(db)

        assert _total(rows) == 10.00

    async def test_a_generation_that_never_became_a_job_still_counts(
        self, tmp_path: Path,
    ):
        """Abandoned and truncation-refused generations are billed the same."""
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            await record_generation(
                db, model="claude-opus-5",
                input_tokens=1_000_000, output_tokens=0,
            )
            rows = await get_spend_by_model(db)

        assert _total(rows) == 5.00

    async def test_submitting_a_job_does_not_add_to_the_total_twice(
        self, tmp_path: Path,
    ):
        """The job row keeps its tokens for the per-job line; the meter reads
        the generations table, so the two must not both be counted."""
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            await record_generation(
                db, model="claude-sonnet-5",
                input_tokens=1_000_000, output_tokens=0,
            )
            await insert_job(db, _make_job(
                input_tokens=1_000_000, output_tokens=0,
                model_used="claude-sonnet-5",
            ))
            rows = await get_spend_by_model(db)

        assert _total(rows) == 2.00


class TestSeedingAnExistingDatabase:
    async def test_history_survives_the_upgrade(self, tmp_path: Path):
        """An existing install must not appear to have spent nothing."""
        path = tmp_path / "jobs.db"
        # A database as it was before the generations table existed.
        async with aiosqlite.connect(path) as db:
            await init_db(db)
            await insert_job(db, _make_job(
                job_id="1", input_tokens=1_000_000, output_tokens=0,
                model_used="claude-opus-5",
            ))
            await db.execute("DELETE FROM generations")
            await db.commit()

        async with aiosqlite.connect(path) as db:
            await init_db(db)          # the upgrade
            rows = await get_spend_by_model(db)

        assert _total(rows) == 5.00

    async def test_seeding_happens_once_however_often_init_runs(
        self, tmp_path: Path,
    ):
        """init_db runs on every connection, so a re-seed would inflate the
        total a little more each time the TUI opened a database."""
        path = tmp_path / "jobs.db"
        async with aiosqlite.connect(path) as db:
            await init_db(db)
            await insert_job(db, _make_job(
                job_id="1", input_tokens=1_000_000, output_tokens=0,
                model_used="claude-opus-5",
            ))
            await db.execute("DELETE FROM generations")
            await db.commit()

        for _ in range(4):
            async with aiosqlite.connect(path) as db:
                await init_db(db)
                rows = await get_spend_by_model(db)

        assert _total(rows) == 5.00

    async def test_a_real_generation_landing_first_does_not_block_the_seed(
        self, tmp_path: Path,
    ):
        """Guarding on the table being empty would have lost the history of
        anyone who generated before the first init_db of the new version."""
        path = tmp_path / "jobs.db"
        async with aiosqlite.connect(path) as db:
            await init_db(db)
            await insert_job(db, _make_job(
                job_id="1", input_tokens=1_000_000, output_tokens=0,
                model_used="claude-opus-5",
            ))
            await db.execute("DELETE FROM generations")
            # A real generation, before any seeding has happened.
            await db.execute(
                "INSERT INTO generations "
                "(generated_at, cluster_name, model, input_tokens, output_tokens) "
                "VALUES (1.0, 'grex', 'claude-sonnet-5', 1000000, 0)"
            )
            await db.commit()

        async with aiosqlite.connect(path) as db:
            await init_db(db)
            rows = await get_spend_by_model(db)

        assert _total(rows) == 7.00       # 5.00 seeded plus 2.00 recorded

    async def test_a_fresh_install_seeds_nothing(self, tmp_path: Path):
        async with aiosqlite.connect(tmp_path / "jobs.db") as db:
            await init_db(db)
            rows = await get_spend_by_model(db)

        assert rows == []
        assert _total(rows) == 0.0


class TestWhatTheScreensShow:
    """The three call sites used to give three different answers for one
    generation. They now share `estimate_cost`, so this checks the strings
    that reach the screen, not just the arithmetic behind them."""

    async def test_the_title_bar_totals_a_mixed_history_correctly(
        self, tmp_path: Path,
    ):
        from clusterpilot.tui.app import TitleBar
        from tests.test_tui_bindings import build_app, offline

        path = tmp_path / "jobs.db"
        async with aiosqlite.connect(path) as db:
            await init_db(db)
            await record_generation(
                db, model="claude-opus-5",
                input_tokens=1_000_000, output_tokens=1_000_000,
            )

        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await app._refresh_cost()
                await pilot.pause()
                shown = app.query_one(TitleBar)._cost_text

        assert "$30.0000" in shown        # Opus 5 at $5 + $25
        assert "$12.0000" not in shown    # what the Sonnet default used to show
        assert "≥" not in shown           # nothing unpriced, so not a floor

    async def test_the_title_bar_marks_a_total_it_cannot_complete(
        self, tmp_path: Path,
    ):
        from clusterpilot.tui.app import TitleBar
        from tests.test_tui_bindings import build_app, offline

        path = tmp_path / "jobs.db"
        async with aiosqlite.connect(path) as db:
            await init_db(db)
            await record_generation(
                db, model="claude-sonnet-5",
                input_tokens=1_000_000, output_tokens=0,
            )
            await record_generation(
                db, model="llama3.2", input_tokens=9_000_000, output_tokens=9_000_000,
            )

        app = build_app(tmp_path)
        with offline():
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                await app._refresh_cost()
                await pilot.pause()
                shown = app.query_one(TitleBar)._cost_text

        assert "≥$2.0000" in shown

    def test_the_job_detail_row_refuses_to_price_an_unknown_model(self):
        from clusterpilot.tui.jobs import _format_meta

        meta = _format_meta(_make_job(
            input_tokens=500_000, output_tokens=500_000, model_used="llama3.2",
        ))
        assert "not priced" in meta
        assert "llama3.2" in meta
        # The old fallback billed it at Sonnet 4.6's rate.
        assert "$9.0000" not in meta

    def test_the_job_detail_row_prices_a_known_model(self):
        from clusterpilot.tui.jobs import _format_meta

        meta = _format_meta(_make_job(
            input_tokens=1_000_000, output_tokens=1_000_000,
            model_used="claude-opus-5",
        ))
        assert "$30.0000" in meta
