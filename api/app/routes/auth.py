"""Clerk webhook receiver: user.created and user.deleted."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models import User
from app.services.clerk import verify_svix_webhook
from app.services.resend import send_welcome_email
from app.services.stripe import get_or_create_customer

router = APIRouter(prefix="/clerk", tags=["auth"])


@router.post("/webhook", status_code=204)
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    body = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    event = verify_svix_webhook(body, headers)
    event_type: str = event.get("type", "")
    data: dict = event.get("data", {})

    if event_type == "user.created":
        clerk_id: str = data["id"]
        email: str = data["email_addresses"][0]["email_address"]

        # Idempotent: skip if already exists (webhook may be replayed)
        existing = await db.execute(select(User).where(User.clerk_id == clerk_id))
        if existing.scalar_one_or_none() is not None:
            return

        stripe_customer_id = await get_or_create_customer(email=email, clerk_id=clerk_id)
        user = User(
            clerk_id=clerk_id,
            email=email,
            stripe_customer_id=stripe_customer_id,
        )
        db.add(user)
        await db.commit()
        await send_welcome_email(email)

    elif event_type == "user.deleted":
        clerk_id = data["id"]
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        user = result.scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.commit()
