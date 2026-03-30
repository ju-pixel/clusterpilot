from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models import User
from app.schemas import KeyOut
from app.services.keys import generate_key, hash_key, key_prefix

router = APIRouter(prefix="/keys", tags=["keys"])


@router.get("", response_model=KeyOut)
async def get_key_info(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the display prefix of the current key, or 404 if none exists."""
    if current_user.managed_api_key_prefix is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No API key issued yet")
    # The full key is never stored — return prefix only for display
    return {"key": f"cp-{current_user.managed_api_key_prefix}••••••••••••••••••••••••••••••••••••", "prefix": current_user.managed_api_key_prefix}


@router.post("", response_model=KeyOut, status_code=status.HTTP_201_CREATED)
async def issue_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue a new key (first-time). Returns the plaintext key once — store it."""
    if current_user.managed_api_key_prefix is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Key already exists. Use POST /keys/rotate to replace it.",
        )
    return await _issue_new_key(current_user, db)


@router.post("/rotate", response_model=KeyOut)
async def rotate_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalidate the current key and issue a new one. Returns plaintext once."""
    return await _issue_new_key(current_user, db)


async def _issue_new_key(user: User, db: AsyncSession) -> dict:
    key = generate_key()
    user.managed_api_key_hash = hash_key(key)
    user.managed_api_key_prefix = key_prefix(key)
    await db.commit()
    return {"key": key, "prefix": user.managed_api_key_prefix}
