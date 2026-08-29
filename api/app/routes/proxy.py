"""Anthropic proxy endpoint.

The local daemon sends:
  Authorization: Bearer cp-<token>
  Body: raw Anthropic Messages API payload (JSON)

This endpoint:
  1. Validates the CP bearer token against the stored bcrypt hash
  2. Checks the user has a live subscription (active or trialing)
  3. Forwards the request to Anthropic using the master API key
  4. Streams the response back

The daemon never holds an Anthropic key, only a CP-issued token.

Three generation paths live here:
  /proxy/v1/messages       raw SSE passthrough for SDK clients
  /proxy/generate          one non-streaming call, one JSON response
  /proxy/generate-stream   newline-delimited JSON over a chunked response

/proxy/generate-stream exists because Fly.io buffers text/event-stream, so the
hosted tier could not stream and the script appeared all at once (issue #41).
application/x-ndjson is not buffered the same way. The client half,
``clusterpilot/jobs/ai_gen.py::_stream_proxy``, still calls /proxy/generate and
is to be switched to this endpoint in a follow-up. That switch must be tested
against the deployed proxy before it merges: buffering behaviour cannot be
reproduced locally, and /proxy/generate must keep working meanwhile so older
installs are unaffected.
"""

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db
from app.models import SUBSCRIBED_STATUSES, User
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


def _extract_token(request: Request) -> str:
    """Pull the CP token from Authorization: Bearer or x-api-key.

    The Anthropic SDK sends x-api-key; direct API calls use Authorization.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.removeprefix("Bearer ")
    if request.headers.get("x-api-key", ""):
        return request.headers["x-api-key"]
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")


async def _authorised_user(request: Request, db: AsyncSession) -> User:
    """Resolve the caller's token and check the subscription gate.

    Raises 401 for an unknown token and 402 when the subscription is neither
    active nor trialing.
    """
    user = await _get_user_by_cp_token(_extract_token(request), db)
    if user.subscription_status not in SUBSCRIBED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active subscription required",
        )
    return user


@router.post("/v1/messages")
async def proxy_messages(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _authorised_user(request, db)

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
    await _authorised_user(request, db)

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


def _ndjson(obj: dict) -> bytes:
    """Encode one NDJSON record, newline terminated."""
    return (json.dumps(obj) + "\n").encode("utf-8")


@router.post("/generate-stream")
async def proxy_generate_stream(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Streaming generation as newline-delimited JSON over a chunked response.

    Accepts the same payload as /proxy/generate. Emits one JSON object per
    line:

        {"text": "..."}                       for every text delta
        {"done": true, "stop_reason": "...",
         "input_tokens": N, "output_tokens": N}   once, last

    On an upstream failure a single {"error": "..."} line is emitted and the
    stream ends. Errors cannot be raised as HTTP status codes once the response
    has begun, so the client must treat an error line as a failed generation.

    Deliberately not text/event-stream: Fly.io buffers that media type, which
    is what stopped the hosted tier streaming in the first place.
    """
    await _authorised_user(request, db)

    payload = await request.json()
    payload["stream"] = True

    async def ndjson_stream():
        input_tokens = 0
        output_tokens = 0
        stop_reason: str | None = None
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    _ANTHROPIC_MESSAGES_URL,
                    json=payload,
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                    },
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield _ndjson({
                            "error": f"Anthropic error {resp.status_code}: "
                                     f"{body.decode('utf-8', 'replace')[:300]}"
                        })
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[len("data:"):].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            event = json.loads(raw)
                        except ValueError:
                            continue

                        kind = event.get("type")
                        if kind == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield _ndjson({"text": text})
                        elif kind == "message_start":
                            usage = event.get("message", {}).get("usage", {})
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                        elif kind == "message_delta":
                            usage = event.get("usage", {})
                            output_tokens = usage.get("output_tokens", output_tokens)
                            stop_reason = event.get("delta", {}).get("stop_reason", stop_reason)
                        elif kind == "error":
                            message = event.get("error", {}).get("type", "upstream error")
                            yield _ndjson({"error": f"Anthropic error: {message}"})
                            return
        except httpx.HTTPError as exc:
            # The exception class only: messages from the HTTP layer can carry
            # request headers, and those carry the master key.
            yield _ndjson({"error": f"Upstream request failed: {type(exc).__name__}"})
            return

        yield _ndjson({
            "done": True,
            "stop_reason": stop_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })

    return StreamingResponse(
        ndjson_stream(),
        media_type="application/x-ndjson",
        headers={
            # Belt and braces against any buffering proxy in front of the app.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
