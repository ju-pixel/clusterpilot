from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_current_user_by_cp_key, get_db
from app.models import User
from app.schemas import NotifyPrefsIn, NotifyPrefsOut

router = APIRouter(prefix="/notify", tags=["notify"])


@router.get("/preferences", response_model=NotifyPrefsOut)
async def get_preferences(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.get("/preferences/daemon", response_model=NotifyPrefsOut)
async def get_preferences_for_daemon(
    current_user: User = Depends(get_current_user_by_cp_key),
) -> User:
    """Same payload as GET /notify/preferences, authenticated by a cp- token.

    The poll daemon holds a CP-issued key rather than a Clerk session, so it
    cannot read the dashboard route. It fetches these once per start and uses
    them to decide which events it sends locally (issue #5).
    """
    return current_user


@router.put("/preferences", response_model=NotifyPrefsOut)
async def update_preferences(
    prefs: NotifyPrefsIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    for field, value in prefs.model_dump().items():
        setattr(current_user, field, value)
    await db.commit()
    await db.refresh(current_user)
    return current_user
