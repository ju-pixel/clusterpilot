"""Monthly generation allowance for the hosted tier.

Three rules, all enforced here so the two generation handlers stay thin:

  1. Hard cap. Once ``total`` for the current UTC month reaches
     ``TOTAL_MONTHLY_CAP`` the request is refused with a 429 naming the date
     the count resets.
  2. Opus fallback. Once ``opus`` reaches ``OPUS_MONTHLY_ALLOWANCE`` a request
     for an Opus model is served by ``FALLBACK_MODEL`` instead, and the caller
     is told so it can say as much in the TUI. The request is never refused
     for this reason alone.
  3. Counting happens only after a 200 from Anthropic. A refused, failed or
     mid-stream-aborted generation costs the user nothing.

The month is a plain "YYYY-MM" string in UTC, so a rollover simply starts
looking at a row that does not exist yet, which reads as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import GenerationUsage, User

_OPUS_PREFIX = "claude-opus"


@dataclass(frozen=True)
class Usage:
    """A user's counts for one month. Zeros when no row exists yet."""

    month: str
    total: int
    opus: int


@dataclass(frozen=True)
class Prepared:
    """The outcome of the pre-flight check for one generation request.

    ``model_used`` is the model that will actually be called upstream, which
    is the fallback rather than the requested model when ``fallback`` is true.
    """

    model_used: str
    fallback: bool
    month: str


def is_opus(model: str) -> bool:
    """True when the model name names an Opus model."""
    return bool(model) and model.startswith(_OPUS_PREFIX)


def current_month(now: Optional[datetime] = None) -> str:
    """The current calendar month in UTC, as "YYYY-MM"."""
    moment = now if now is not None else datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


def resets_on(month: str) -> str:
    """The first day of the month after ``month``, as an ISO date string."""
    year, number = (int(part) for part in month.split("-"))
    if number == 12:
        year, number = year + 1, 1
    else:
        number += 1
    return date(year, number, 1).isoformat()


def remaining(usage: Usage) -> Tuple[int, int]:
    """Generations left this month as (opus, total). Never negative."""
    return (
        max(0, settings.opus_monthly_allowance - usage.opus),
        max(0, settings.total_monthly_cap - usage.total),
    )


async def get_usage(db: AsyncSession, user_id: int, month: str) -> Usage:
    """Read one user's counts for ``month``, or zeros when there is no row."""
    result = await db.execute(
        select(GenerationUsage).where(
            GenerationUsage.user_id == user_id,
            GenerationUsage.month == month,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return Usage(month=month, total=0, opus=0)
    return Usage(month=month, total=row.total, opus=row.opus)


async def check_and_prepare(db: AsyncSession, user: User, payload: dict) -> Prepared:
    """Apply the cap and the Opus fallback before an upstream call is made.

    Mutates ``payload["model"]`` in place when the Opus allowance is spent, so
    the caller can forward the payload unchanged. Raises HTTPException 429 at
    the total cap.
    """
    month = current_month()
    usage = await get_usage(db, user.id, month)

    if usage.total >= settings.total_monthly_cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly generation allowance of {settings.total_monthly_cap} "
                f"reached; it resets on {resets_on(month)}."
            ),
        )

    requested = payload.get("model") or ""
    if is_opus(requested) and usage.opus >= settings.opus_monthly_allowance:
        payload["model"] = settings.fallback_model
        return Prepared(model_used=settings.fallback_model, fallback=True, month=month)

    return Prepared(model_used=requested, fallback=False, month=month)


async def record_success(db: AsyncSession, user_id: int, model_used: str) -> Usage:
    """Count one successful generation and return the month's new totals.

    The increment is an UPDATE with a SQL-side expression rather than a
    read-modify-write, so two generations served by two machines at once
    cannot lose a count. The INSERT that creates the first row of a month is
    the one place a race can still collide; the unique constraint catches it
    and the increment is retried against the row the other request created.
    """
    month = current_month()
    opus_delta = 1 if is_opus(model_used) else 0

    result = await db.execute(
        update(GenerationUsage)
        .where(
            GenerationUsage.user_id == user_id,
            GenerationUsage.month == month,
        )
        .values(
            total=GenerationUsage.total + 1,
            opus=GenerationUsage.opus + opus_delta,
        )
        .execution_options(synchronize_session=False)
    )

    if result.rowcount == 0:
        db.add(GenerationUsage(user_id=user_id, month=month, total=1, opus=opus_delta))
        try:
            await db.commit()
        except IntegrityError:
            # Another request inserted this month's row between the UPDATE and
            # the INSERT. Fall back to incrementing that row.
            await db.rollback()
            await db.execute(
                update(GenerationUsage)
                .where(
                    GenerationUsage.user_id == user_id,
                    GenerationUsage.month == month,
                )
                .values(
                    total=GenerationUsage.total + 1,
                    opus=GenerationUsage.opus + opus_delta,
                )
                .execution_options(synchronize_session=False)
            )
            await db.commit()
    else:
        await db.commit()

    return await get_usage(db, user_id, month)
