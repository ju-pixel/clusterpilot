"""Measuring reserved resource time from squeue, when sacct cannot be reached.

Issue #47: sacct needs slurmdbd, which Alliance login nodes cannot reach, so
on the clusters ClusterPilot is mostly used on there is no accounting record
to read after a job ends. squeue talks to slurmctld, which does answer, but
only while the job is in the queue. So the daemon measures as the job runs:
every poll it knows how many tasks are running, and charges that many
per-task allocations for the time since the previous poll.

The array case is the point of it. A single start-to-finish figure would
charge one task's worth of resource for the whole wall-clock span, which is
wrong in both directions: it undercounts tasks running side by side, and
overcounts an array whose tasks are queued most of the time.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from clusterpilot.cluster.slurm import JobAllocation, _parse_allocation
from clusterpilot.db import (
    JobRecord,
    accumulate_reserved,
    get_job,
    init_db,
    insert_job,
    update_allocation,
)

# Real Narval output, from squeue -O tres-alloc on 2026-08-29.
_GPU_LINE = "cpu=4,mem=64G,node=1,billing=16000,gres/gpu=4,gres/gpu:a100=4"
_MIG_LINE = "cpu=4,mem=32G,node=1,billing=1333,gres/gpu=1,gres/gpu:a100_1g.5gb=1"
_CPU_LINE = "cpu=8,mem=49600M,node=1,billing=8"


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="12345", job_name="sweep", cluster_name="narval",
        host="narval.alliancecan.ca", user="juliaf", account="def-stamps",
        partition="", script_path="/s.sh", working_dir="/w", local_dir="/l",
        walltime="08:00:00", status="RUNNING", submitted_at=time.time(),
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


@pytest.fixture
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        await insert_job(conn, _make_job())
        yield conn


class TestParsingRealNarvalOutput:
    def test_a_gpu_job(self):
        alloc = _parse_allocation(_GPU_LINE)
        assert (alloc.cpus, alloc.gpus, alloc.nodes) == (4, 4, 1)
        assert alloc.billing == 16000

    def test_the_typed_gres_key_does_not_double_count(self):
        # Narval prints gres/gpu=4 and gres/gpu:a100=4 on the same line.
        assert _parse_allocation(_GPU_LINE).gpus == 4

    def test_a_mig_slice(self):
        alloc = _parse_allocation(_MIG_LINE)
        assert alloc.gpus == 1
        assert alloc.billing == 1333

    def test_a_cpu_job_has_no_gpus(self):
        alloc = _parse_allocation(_CPU_LINE)
        assert alloc.gpus is None
        assert (alloc.cpus, alloc.billing) == (8, 8)

    def test_billing_is_not_proportional_to_cpus(self):
        # The whole reason billing is captured: four CPUs with four A100s
        # bills at 16000, eight plain CPUs at 8. Reporting the first as
        # "4 core-hours" understates it by three orders of magnitude.
        gpu = _parse_allocation(_GPU_LINE)
        cpu = _parse_allocation(_CPU_LINE)
        assert gpu.cpus < cpu.cpus
        assert gpu.billing > cpu.billing * 100

    def test_a_truncated_line_is_refused_rather_than_half_read(self):
        # squeue's fixed-width fields cut the string silently; half an
        # allocation yields a confident, wrong figure.
        truncated = "cpu=8,mem=49600M,nod" + "x" * 200
        assert _parse_allocation(truncated).is_empty

    def test_empty_output(self):
        assert _parse_allocation("").is_empty


class TestAccumulation:
    async def test_one_running_task_charges_its_allocation(self, db):
        await update_allocation(
            db, "12345", "narval",
            JobAllocation(cpus=4, gpus=1, nodes=1, billing=1333),
            measured_at=1000.0,
        )
        await accumulate_reserved(
            db, "12345", "narval",
            running_tasks=1, seconds=60.0,
            cpus=4, gpus=1, billing=1333, now=1060.0,
        )
        job = await get_job(db, "12345", "narval")
        assert job.core_seconds == 240.0
        assert job.gpu_seconds == 60.0
        assert job.billing_seconds == 1333 * 60
        assert job.accounting_source == "measured"

    async def test_ten_running_tasks_charge_ten_allocations(self, db):
        # The array case: a single start-to-finish figure would charge one.
        await accumulate_reserved(
            db, "12345", "narval",
            running_tasks=10, seconds=60.0,
            cpus=4, gpus=None, billing=8, now=1060.0,
        )
        job = await get_job(db, "12345", "narval")
        assert job.core_seconds == 10 * 4 * 60

    async def test_it_sums_across_polls(self, db):
        for _ in range(3):
            await accumulate_reserved(
                db, "12345", "narval",
                running_tasks=2, seconds=30.0,
                cpus=4, gpus=None, billing=None, now=1.0,
            )
        job = await get_job(db, "12345", "narval")
        assert job.core_seconds == 3 * 2 * 4 * 30

    async def test_a_changing_task_count_is_followed(self, db):
        # Tasks of an array start and finish at different times, which is
        # exactly what a single elapsed figure cannot represent.
        await accumulate_reserved(db, "12345", "narval", running_tasks=8,
                                  seconds=60.0, cpus=1, gpus=None, billing=None, now=1.0)
        await accumulate_reserved(db, "12345", "narval", running_tasks=3,
                                  seconds=60.0, cpus=1, gpus=None, billing=None, now=2.0)
        job = await get_job(db, "12345", "narval")
        assert job.core_seconds == (8 * 60) + (3 * 60)

    async def test_queued_time_is_never_charged(self, db):
        await accumulate_reserved(
            db, "12345", "narval",
            running_tasks=0, seconds=600.0,
            cpus=4, gpus=1, billing=1333, now=2000.0,
        )
        job = await get_job(db, "12345", "narval")
        assert job.core_seconds is None
        assert job.accounting_source == ""
        # The clock still advances, so the next interval is not double charged.
        assert job.measured_at == 2000.0

    async def test_an_unknown_resource_contributes_nothing(self, db):
        await accumulate_reserved(
            db, "12345", "narval",
            running_tasks=1, seconds=60.0,
            cpus=4, gpus=None, billing=None, now=1.0,
        )
        job = await get_job(db, "12345", "narval")
        assert job.core_seconds == 240.0
        assert job.gpu_seconds == 0.0

    async def test_measured_never_overwrites_a_real_accounting_record(self, db):
        from clusterpilot.cluster.slurm import JobAccounting
        from clusterpilot.db import update_accounting
        await update_accounting(db, "12345", "narval", JobAccounting(
            cpus=4, runtime_seconds=3600, core_seconds=14400.0, tasks=1,
        ))
        assert (await get_job(db, "12345", "narval")).accounting_source == "sacct"
        await accumulate_reserved(
            db, "12345", "narval",
            running_tasks=1, seconds=60.0, cpus=4, gpus=None, billing=None, now=1.0,
        )
        job = await get_job(db, "12345", "narval")
        assert job.accounting_source == "sacct", "sacct must stay authoritative"


class TestAllocationStorage:
    async def test_round_trips(self, db):
        await update_allocation(
            db, "12345", "narval",
            JobAllocation(cpus=4, gpus=4, nodes=1, billing=16000),
            measured_at=1000.0,
        )
        job = await get_job(db, "12345", "narval")
        assert (job.alloc_cpus, job.alloc_gpus, job.alloc_nodes) == (4, 4, 1)
        assert job.alloc_billing == 16000
        assert job.measured_at == 1000.0

    async def test_an_empty_allocation_is_a_no_op(self, db):
        await update_allocation(
            db, "12345", "narval",
            JobAllocation(cpus=4, billing=8), measured_at=1000.0,
        )
        await update_allocation(
            db, "12345", "narval", JobAllocation(), measured_at=2000.0,
        )
        job = await get_job(db, "12345", "narval")
        assert job.alloc_cpus == 4

    async def test_the_first_measurement_time_is_kept(self, db):
        # COALESCE, so a second allocation read does not lose the interval
        # already measured against the first.
        await update_allocation(db, "12345", "narval",
                                JobAllocation(cpus=4), measured_at=1000.0)
        await update_allocation(db, "12345", "narval",
                                JobAllocation(cpus=4), measured_at=9999.0)
        assert (await get_job(db, "12345", "narval")).measured_at == 1000.0
