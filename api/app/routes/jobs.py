from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models import Job, User
from app.schemas import JobOut, JobUpsert

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
async def list_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Job]:
    result = await db.execute(
        select(Job)
        .where(Job.user_id == current_user.id)
        .order_by(Job.submitted_at.desc())
        .limit(200)
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
    current_user: User = Depends(get_current_user),
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
