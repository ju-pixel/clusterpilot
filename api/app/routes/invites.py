"""Invite code routes for PI seat bundles."""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models import InviteCode, User
from app.schemas import InviteCodeOut, RedeemRequest

router = APIRouter(prefix="/invites", tags=["invites"])


@router.get("", response_model=List[InviteCodeOut])
async def list_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InviteCode]:
    """Return all invite codes issued by the current user (PI view)."""
    result = await db.execute(
        select(InviteCode).where(InviteCode.pi_user_id == current_user.id)
    )
    return list(result.scalars().all())


@router.post("/redeem", status_code=200)
async def redeem_invite(
    body: RedeemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Redeem an invite code. Activates the current user under the PI's subscription."""
    if current_user.subscription_status in ("active", "trialing"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is already active.",
        )

    result = await db.execute(
        select(InviteCode).where(InviteCode.code == body.code.upper().strip())
    )
    invite = result.scalar_one_or_none()

    if invite is None or invite.redeemed_by_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or already-used invite code.",
        )

    if invite.pi_user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot redeem your own invite code.",
        )

    invite.redeemed_by_user_id = current_user.id
    invite.redeemed_at = datetime.now(timezone.utc)
    current_user.subscription_status = "active"
    current_user.sponsored_by_user_id = invite.pi_user_id
    await db.commit()

    return {"status": "active"}
