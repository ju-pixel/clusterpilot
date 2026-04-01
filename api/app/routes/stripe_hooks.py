"""Stripe webhook receiver."""

import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models import InviteCode, User
from app.services.resend import (
    send_payment_failed_email,
    send_pi_invite_codes_email,
    send_subscription_started_email,
)
from app.services.stripe import construct_stripe_event

router = APIRouter(prefix="/stripe", tags=["stripe"])


@router.post("/webhook", status_code=204)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = construct_stripe_event(body, sig)

    event_type: str = event["type"]
    data_obj: dict = event["data"]["object"]

    if event_type == "checkout.session.completed":
        customer_id: str = data_obj.get("customer", "")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user is not None:
            user.subscription_status = "active"

            if data_obj.get("metadata", {}).get("type") == "pi_bundle":
                # Generate one invite code per seat purchased and email them to the PI
                quantity = int(data_obj.get("metadata", {}).get("quantity", "0"))
                subscription_id: str = data_obj.get("subscription", "")
                codes: list[str] = []
                for _ in range(quantity):
                    code = secrets.token_hex(4).upper()
                    db.add(InviteCode(
                        code=code,
                        pi_user_id=user.id,
                        stripe_subscription_id=subscription_id,
                    ))
                    codes.append(code)
                await db.commit()
                await send_pi_invite_codes_email(user.email, codes)
            else:
                await db.commit()
                await send_subscription_started_email(user.email)

    elif event_type == "customer.subscription.updated":
        customer_id = data_obj.get("customer", "")
        stripe_status: str = data_obj.get("status", "")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user is not None:
            user.subscription_status = "active" if stripe_status == "active" else stripe_status
            await db.commit()

    elif event_type == "customer.subscription.deleted":
        customer_id = data_obj.get("customer", "")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user is not None:
            user.subscription_status = "cancelled"
            # Deactivate any researchers sponsored by this PI
            sponsored_result = await db.execute(
                select(User).where(User.sponsored_by_user_id == user.id)
            )
            for sponsored_user in sponsored_result.scalars().all():
                sponsored_user.subscription_status = "free"
                sponsored_user.sponsored_by_user_id = None
            await db.commit()

    elif event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer", "")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user is not None:
            await send_payment_failed_email(user.email)
