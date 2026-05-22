import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, get_engine
from app.routes import auth, email, health, invites, jobs, keys, notify, proxy, stripe_hooks, users

logger = logging.getLogger(__name__)


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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Starlette installs Exception/500 handlers on ServerErrorMiddleware which sits OUTSIDE CORSMiddleware, so we set CORS headers manually here or the browser shows a misleading "no Access-Control-Allow-Origin" error. Class name only, because exception messages can leak secrets (e.g. Stripe AuthenticationError includes the key prefix).
    logger.exception(
        "Unhandled %s in %s %s",
        exc.__class__.__name__, request.method, request.url.path,
    )
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": exc.__class__.__name__},
    )
    origin = request.headers.get("origin")
    if origin in settings.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(email.router)
app.include_router(stripe_hooks.router)
app.include_router(jobs.router)
app.include_router(keys.router)
app.include_router(notify.router)
app.include_router(users.router)
app.include_router(invites.router)
app.include_router(proxy.router)
