"""Clerk JWT verification and Svix webhook signature verification."""

import time
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings

_bearer = HTTPBearer()

# JWKS cache: keys expire after 1 hour (Clerk rotates slowly)
_JWKS_TTL = 3600
_jwks_cache: dict[str, object] = {}
_jwks_fetched_at: float = 0.0


async def _get_jwks() -> dict:
    global _jwks_fetched_at, _jwks_cache
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache  # type: ignore[return-value]
    # Derive JWKS URL from Clerk secret key prefix (sk_live_XXX → publishable domain)
    # Clerk JWKS is always at https://<frontend-api>/.well-known/jwks.json
    # The issuer in the JWT contains the frontend API URL.
    # We fetch it lazily from the JWT header on first call.
    raise RuntimeError("Call _refresh_jwks with the issuer URL from the JWT header.")


async def _refresh_jwks(issuer: str) -> dict:
    global _jwks_fetched_at, _jwks_cache
    url = f"{issuer}/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
    _jwks_cache = resp.json()
    _jwks_fetched_at = time.monotonic()
    return _jwks_cache  # type: ignore[return-value]


async def verify_clerk_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Verify a Clerk-issued JWT and return the clerk_id (sub claim)."""
    token = credentials.credentials
    try:
        # Decode header only to get kid + issuer without verification
        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")
        unverified_claims = jwt.get_unverified_claims(token)
        issuer = unverified_claims.get("iss", "")

        now = time.monotonic()
        global _jwks_cache, _jwks_fetched_at
        if not _jwks_cache or (now - _jwks_fetched_at) >= _JWKS_TTL:
            await _refresh_jwks(issuer)

        # Find matching key by kid
        keys = _jwks_cache.get("keys", [])
        signing_key = next((k for k in keys if k.get("kid") == kid), None)
        if signing_key is None:
            # Key not in cache — refresh once and retry
            await _refresh_jwks(issuer)
            keys = _jwks_cache.get("keys", [])
            signing_key = next((k for k in keys if k.get("kid") == kid), None)
        if signing_key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown signing key")

        public_key = jwk.construct(signing_key)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return payload["sub"]

    except (JWTError, KeyError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc


def verify_svix_webhook(request_body: bytes, headers: dict[str, str]) -> dict:
    """Verify a Clerk webhook payload signed by Svix.

    Raises HTTPException 400 on invalid signature.
    Returns the parsed event dict on success.
    """
    wh = Webhook(settings.clerk_webhook_secret)
    try:
        return wh.verify(request_body, headers)  # type: ignore[return-value]
    except WebhookVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Clerk webhook signature: {exc}",
        ) from exc
