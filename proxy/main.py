"""ClusterPilot beta proxy — validates beta tokens and forwards to Anthropic.

Tokens are stored in the BETA_TOKENS environment variable as a
comma-separated list of token:name pairs, e.g.:

    BETA_TOKENS="abc123:Alice,def456:Bob"

Set via Fly.io secrets:
    fly secrets set BETA_TOKENS="..."  ANTHROPIC_API_KEY="sk-..."

Rate limiting is in-memory (resets on process restart). Restarts on
Fly.io scale-to-zero are infrequent; the daily limit is an abuse
safeguard, not a precise billing control.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

app = FastAPI(title="ClusterPilot Beta Proxy", docs_url=None, redoc_url=None)

_ANTHROPIC_BASE = "https://api.anthropic.com"
_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
_DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "30"))

# In-memory usage counters: {token: {date_str: count}}
_usage: dict[str, dict[str, int]] = defaultdict(dict)


def _load_tokens() -> dict[str, str]:
    """Parse BETA_TOKENS env var → {token: name}."""
    raw = os.environ.get("BETA_TOKENS", "")
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            token, name = entry.split(":", 1)
            result[token.strip()] = name.strip()
    return result


def _check_rate_limit(token: str) -> bool:
    """Increment today's counter for token. Returns False if limit exceeded."""
    today = str(date.today())
    counts = _usage[token]
    for d in list(counts):  # drop stale dates
        if d != today:
            del counts[d]
    n = counts.get(today, 0)
    if n >= _DAILY_LIMIT:
        return False
    counts[today] = n + 1
    return True


async def _close_upstream(client: httpx.AsyncClient, response: httpx.Response) -> None:
    await response.aclose()
    await client.aclose()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/v1/messages")
async def proxy_messages(request: Request, background_tasks: BackgroundTasks):
    """Forward a messages request to Anthropic, authenticated by beta token."""
    # The Anthropic SDK sends the key in the x-api-key header.
    token = request.headers.get("x-api-key", "").strip()

    tokens = _load_tokens()
    if not token or token not in tokens:
        raise HTTPException(status_code=401, detail="Invalid or missing beta token.")

    if not _check_rate_limit(token):
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit of {_DAILY_LIMIT} requests reached. Try again tomorrow.",
        )

    if not _ANTHROPIC_KEY:
        raise HTTPException(status_code=503, detail="Proxy misconfigured — contact the administrator.")

    body = await request.body()

    forward_headers: dict[str, str] = {
        "x-api-key": _ANTHROPIC_KEY,
        "content-type": "application/json",
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
    }
    if "anthropic-beta" in request.headers:
        forward_headers["anthropic-beta"] = request.headers["anthropic-beta"]

    name = tokens[token]
    today = str(date.today())
    day_count = _usage[token].get(today, 0)
    log.info("request token=%s… name=%r day_requests=%d", token[:8], name, day_count)

    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    upstream_req = client.build_request(
        "POST",
        f"{_ANTHROPIC_BASE}/v1/messages",
        content=body,
        headers=forward_headers,
    )
    upstream_resp = await client.send(upstream_req, stream=True)

    background_tasks.add_task(_close_upstream, client, upstream_resp)

    return StreamingResponse(
        upstream_resp.aiter_bytes(),
        status_code=upstream_resp.status_code,
        media_type=upstream_resp.headers.get("content-type", "text/event-stream"),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "active_tokens": len(_load_tokens())}


@app.get("/admin/usage")
async def usage(request: Request):
    """Per-token usage summary for today. Requires x-admin-key header."""
    if not _ADMIN_KEY or request.headers.get("x-admin-key") != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden.")
    tokens = _load_tokens()
    today = str(date.today())
    return {
        name: {
            "token_prefix": token[:8] + "…",
            "today_requests": _usage[token].get(today, 0),
            "daily_limit": _DAILY_LIMIT,
        }
        for token, name in tokens.items()
    }
