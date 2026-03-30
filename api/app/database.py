from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


def _normalise_url(url: str) -> tuple[str, dict]:
    """Normalise the DATABASE_URL for asyncpg.

    Fly.io sets DATABASE_URL as ``postgres://...?sslmode=require``.
    SQLAlchemy's asyncpg dialect cannot forward ``sslmode`` correctly
    across all versions.  We strip it from the query string and return
    it as a ``connect_args`` dict instead.

    Returns (normalised_url, connect_args).
    """
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    sslmode_values = params.pop("sslmode", [])
    new_query = urlencode({k: v[0] for k, v in params.items()})
    normalised = urlunparse(parsed._replace(query=new_query))

    # asyncpg defaults to "prefer" SSL, which tries SSL first then falls back.
    # Fly.io internal Postgres hard-resets on SSL negotiation rather than
    # sending the standard "SSL not supported" response, so asyncpg cannot
    # fall back gracefully.  Explicitly disable SSL so no negotiation occurs.
    connect_args: dict = {"ssl": False}
    return normalised, connect_args


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        from app.config import settings
        url, connect_args = _normalise_url(settings.database_url)
        _engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session
