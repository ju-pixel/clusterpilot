from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import User
from app.services.clerk import verify_clerk_jwt
from app.services.keys import verify_key


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def get_current_user(
    clerk_id: str = Depends(verify_clerk_jwt),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found — sign-in with Clerk first",
        )
    return user


async def get_current_user_by_cp_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate via ClusterPilot-issued API key (cp-XXXX).

    Used by daemon endpoints (e.g. POST /jobs) where the caller holds a
    CP key, not a Clerk JWT session.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = auth_header.removeprefix("Bearer ")

    if not token.startswith("cp-"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    prefix = token[3:7]
    result = await db.execute(
        select(User).where(
            User.managed_api_key_prefix == prefix,
            User.managed_api_key_hash.isnot(None),
        )
    )
    candidates = result.scalars().all()
    for user in candidates:
        if verify_key(token, user.managed_api_key_hash):  # type: ignore[arg-type]
            return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
