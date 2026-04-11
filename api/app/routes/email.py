"""Contact form and Resend inbound email forwarding."""

import json
import logging
import re

import httpx
import resend
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.resend_api_key

router = APIRouter(prefix="/email", tags=["email"])

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ─── contact form ─────────────────────────────────────────────────────────────

class ContactRequest(BaseModel):
    name: str
    email: str
    message: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required.")
        if len(v) > 200:
            raise ValueError("Name is too long.")
        return v

    @field_validator("email")
    @classmethod
    def email_valid(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address.")
        return v

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message is required.")
        if len(v) > 5000:
            raise ValueError("Message is too long (max 5000 characters).")
        return v


@router.post("/contact")
async def contact(body: ContactRequest) -> dict:
    """Send a support/contact message to hello@clusterpilot.sh."""
    resend.Emails.send({
        "from": settings.resend_from_address,
        "to": [settings.resend_forward_to],
        "reply_to": body.email,
        "subject": f"[ClusterPilot Support] Message from {body.name}",
        "text": f"Name: {body.name}\nEmail: {body.email}\n\n{body.message}",
    })
    return {"ok": True}


# ─── Resend inbound webhook (email forwarding) ────────────────────────────────

@router.post("/inbound")
async def inbound_email(request: Request) -> dict:
    """
    Webhook called by Resend when an email arrives at @clusterpilot.sh.
    Verifies the Svix signature, then forwards the email to resend_forward_to.
    """
    # Read raw bytes first — Svix signs the exact body bytes.
    raw_body = await request.body()

    # Verify Svix signature.
    svix_headers = {
        "svix-id":        request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    wh = Webhook(settings.resend_webhook_secret)
    try:
        wh.verify(raw_body, svix_headers)
    except WebhookVerificationError as exc:
        logger.warning("Resend inbound: invalid Svix signature — %s", exc)
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    try:
        payload: dict = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    data = payload.get("data") or payload
    email_id = data.get("email_id")

    if not email_id:
        logger.warning("Resend inbound webhook: missing email_id in payload.")
        raise HTTPException(status_code=400, detail="Missing email_id.")

    # Pick display name based on which address the email was sent to
    recipients: list[str] = data.get("to") or []
    first_recipient = recipients[0] if recipients else "hello@clusterpilot.sh"
    if "privacy" in first_recipient:
        from_display = "ClusterPilot Privacy <privacy@clusterpilot.sh>"
    else:
        from_display = settings.resend_from_address

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://api.resend.com/emails/{email_id}/forward",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "to": [settings.resend_forward_to],
                "from": from_display,
            },
        )

    if r.status_code >= 400:
        logger.error("Resend forward failed: %s %s", r.status_code, r.text)
        raise HTTPException(status_code=502, detail="Failed to forward email.")

    return {"ok": True}
