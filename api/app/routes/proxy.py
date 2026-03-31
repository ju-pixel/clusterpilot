"""Anthropic proxy endpoint.

The local daemon sends:
  Authorization: Bearer cp-<token>
  Body: raw Anthropic Messages API payload (JSON)

This endpoint:
  1. Validates the CP bearer token against the stored bcrypt hash
  2. Checks the user has an active subscription
  3. Forwards the request to Anthropic using the master API key
  4. Streams the response back

The daemon never holds an Anthropic key — only a CP-issued token.
"""

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.models import User
from app.services.keys import verify_key

router = APIRouter(prefix="/proxy", tags=["proxy"])

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


async def _get_user_by_cp_token(token: str, db: AsyncSession) -> User:
    """Look up the user whose managed key matches token. Raises 401 on mismatch."""
    if not token.startswith("cp-"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    # We must check every user whose key prefix matches the token's prefix
    # (prefix = first 4 chars after "cp-"), to avoid a full-table scan on every request.
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


@router.post("/v1/messages")
async def proxy_messages(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Accept token from either Authorization: Bearer <token> or x-api-key: <token>.
    # The Anthropic SDK sends x-api-key; direct API calls use Authorization: Bearer.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
    elif request.headers.get("x-api-key", ""):
        token = request.headers["x-api-key"]
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = await _get_user_by_cp_token(token, db)

    if user.subscription_status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active subscription required",
        )

    body = await request.body()

    async def stream_anthropic() -> bytes:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                _ANTHROPIC_MESSAGES_URL,
                content=body,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(stream_anthropic(), media_type="text/event-stream")


@router.post("/generate")
async def proxy_generate(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Non-streaming generation endpoint for clients that cannot consume SSE.

    Accepts the same payload as /v1/messages (minus stream flag).
    Returns {"text": "<full script>", "input_tokens": N, "output_tokens": N}.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
    elif request.headers.get("x-api-key", ""):
        token = request.headers["x-api-key"]
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = await _get_user_by_cp_token(token, db)

    if user.subscription_status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active subscription required",
        )

    payload = await request.json()
    payload["stream"] = False  # force non-streaming

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            _ANTHROPIC_MESSAGES_URL,
            json=payload,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Anthropic error: {resp.text[:300]}",
        )

    data = resp.json()
    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    usage = data.get("usage", {})
    return JSONResponse({
        "text": text,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    })
