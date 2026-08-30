from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_current_user_by_cp_key, get_db
from app.models import Job, User
from app.schemas import JobOut, JobUpsert

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = Query(100, ge=1, le=200),
    before: Optional[datetime] = Query(
        None,
        description="Return jobs submitted strictly before this time. Use the "
                    "submitted_at of the oldest job you already have.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Job]:
    """One page of the user's jobs, newest first.

    Paged on ``submitted_at`` rather than an offset. An offset shifts under
    the reader every time the daemon syncs a new job, so page two silently
    repeats or skips rows; a cursor does not. Jobs with no submitted_at are
    excluded from paging rather than sorted arbitrarily.
    """
    query = select(Job).where(Job.user_id == current_user.id)
    if before is not None:
        query = query.where(Job.submitted_at < before)
    result = await db.execute(
        query.order_by(Job.submitted_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Job:
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("", response_model=JobOut, status_code=status.HTTP_200_OK)
async def upsert_job(
    payload: JobUpsert,
    current_user: User = Depends(get_current_user_by_cp_key),
    db: AsyncSession = Depends(get_db),
) -> Job:
    """Idempotent upsert: daemon calls this on each state change.

    If a job with (user_id, slurm_job_id, cluster_name) already exists it is
    updated in-place; otherwise a new row is inserted.
    """
    result = await db.execute(
        select(Job).where(
            Job.user_id == current_user.id,
            Job.slurm_job_id == payload.slurm_job_id,
            Job.cluster_name == payload.cluster_name,
        )
    )
    job = result.scalar_one_or_none()

    if job is None:
        job = Job(user_id=current_user.id)
        db.add(job)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(job, field, value)

    await db.commit()
    await db.refresh(job)
    return job
