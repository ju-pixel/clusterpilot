"""Tests for the job upsert route and what it now carries.

The dashboard can only render what the daemon sends and the API stores. These
pin the fields added for the usage report: the accounting numbers travel, an
absent number stays NULL rather than becoming a zero the report would add up,
and a client that predates the fields is still accepted.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Job, User
from app.routes.jobs import list_jobs, upsert_job
from app.schemas import JobUpsert


async def _user(db) -> User:
    user = User(clerk_id="user_test", email="julia@example.com", subscription_status="active")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _payload(**kwargs) -> JobUpsert:
    defaults = dict(
        slurm_job_id="8271604",
        job_name="spin_glass_L64",
        cluster_name="narval",
        status="COMPLETED",
        submitted_at=datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return JobUpsert(**defaults)


class TestAccountingFields:
    async def test_the_numbers_are_stored(self, db):
        user = await _user(db)
        job = await upsert_job(_payload(
            account="def-stamps",
            array_spec="0-99",
            status_detail="5R/27PD",
            efficiency="CPU 12%, mem 6% of 16 GB",
            exit_code="0:0",
            alloc_cpus=4, alloc_gpus=1, alloc_nodes=1,
            runtime_seconds=3600, core_seconds=14400.0, gpu_seconds=3600.0,
        ), current_user=user, db=db)

        assert job.account == "def-stamps"
        assert job.array_spec == "0-99"
        assert job.status_detail == "5R/27PD"
        assert job.efficiency == "CPU 12%, mem 6% of 16 GB"
        assert job.exit_code == "0:0"
        assert job.alloc_cpus == 4
        assert job.alloc_gpus == 1
        assert job.alloc_nodes == 1
        assert job.runtime_seconds == 3600
        assert job.core_seconds == 14400.0
        assert job.gpu_seconds == 3600.0

    async def test_a_client_that_does_not_send_them_is_still_accepted(self, db):
        # The client and the API deploy independently, in either order.
        user = await _user(db)
        job = await upsert_job(_payload(), current_user=user, db=db)
        assert job.slurm_job_id == "8271604"
        assert job.core_seconds is None
        assert job.alloc_gpus is None

    async def test_an_unreported_figure_stays_null_not_zero(self, db):
        user = await _user(db)
        job = await upsert_job(_payload(
            alloc_cpus=8, core_seconds=480.0, alloc_gpus=None, gpu_seconds=None,
        ), current_user=user, db=db)
        assert job.core_seconds == 480.0
        assert job.alloc_gpus is None
        assert job.gpu_seconds is None

    async def test_a_later_update_fills_in_what_the_first_lacked(self, db):
        # The daemon syncs on every state change: RUNNING has no accounting
        # yet, and the terminal sync is where the numbers arrive.
        user = await _user(db)
        await upsert_job(_payload(status="RUNNING"), current_user=user, db=db)
        job = await upsert_job(_payload(
            status="COMPLETED", core_seconds=14400.0, alloc_cpus=4,
        ), current_user=user, db=db)

        assert job.status == "COMPLETED"
        assert job.core_seconds == 14400.0
        rows = (await db.execute(select(Job))).scalars().all()
        assert len(rows) == 1, "the upsert must stay idempotent"

    async def test_they_come_back_out_on_the_job_list(self, db):
        user = await _user(db)
        await upsert_job(_payload(
            core_seconds=14400.0, alloc_gpus=1, status_detail="5R/27PD",
        ), current_user=user, db=db)
        jobs = await list_jobs(current_user=user, db=db)
        assert len(jobs) == 1
        assert jobs[0].core_seconds == 14400.0
        assert jobs[0].alloc_gpus == 1
        assert jobs[0].status_detail == "5R/27PD"
