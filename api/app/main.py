from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, get_engine
from app.routes import auth, health, jobs, keys, notify, proxy, stripe_hooks, users


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Create tables if they do not exist (Alembic handles production migrations;
    # this covers first-run local development without requiring a migration step).
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await get_engine().dispose()


app = FastAPI(
    title="ClusterPilot API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(stripe_hooks.router)
app.include_router(jobs.router)
app.include_router(keys.router)
app.include_router(notify.router)
app.include_router(users.router)
app.include_router(proxy.router)
