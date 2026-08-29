"""Test settings for the hosted API.

``app.config.Settings`` has required fields and is instantiated at import time,
so every value it needs must be in the environment before any ``app.*`` module
is imported. conftest is imported before the test modules, which makes this the
right place for it. None of these are real credentials.
"""
from __future__ import annotations

import os

import pytest

_TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "CLERK_SECRET_KEY": "sk_test_not_a_real_key",
    "CLERK_WEBHOOK_SECRET": "whsec_test_not_a_real_secret",
    "STRIPE_SECRET_KEY": "sk_test_not_a_real_key",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_not_a_real_secret",
    "STRIPE_PRICE_ID_MONTHLY": "price_test_monthly",
    "STRIPE_PRICE_ID_ANNUAL": "price_test_annual",
    "RESEND_API_KEY": "re_test_not_a_real_key",
    "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
    "ENVIRONMENT": "test",
}

for _name, _value in _TEST_ENV.items():
    os.environ.setdefault(_name, _value)


@pytest.fixture
async def db_factory():
    """A session factory over a throwaway in-memory SQLite database.

    StaticPool keeps every session on the one connection, so a session opened
    inside a streaming response sees the rows the request-scoped session wrote.
    No SSH, no Postgres and no network: the schema comes straight from the ORM
    metadata, which is what the Alembic migration also creates.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from app import models  # noqa: F401  registers the tables on Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest.fixture
async def db(db_factory):
    """A single session over the throwaway database, as a route would receive."""
    async with db_factory() as session:
        yield session
