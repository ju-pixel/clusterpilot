"""Stripe webhook receiver."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models import User
from app.services.resend import send_payment_failed_email, send_subscription_started_email
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
            await db.commit()
            await send_subscription_started_email(user.email)

    elif event_type in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        customer_id = data_obj.get("customer", "")
        stripe_status: str = data_obj.get("status", "")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user is not None:
            # Map Stripe subscription status to our simplified model
            user.subscription_status = "active" if stripe_status == "active" else stripe_status
            await db.commit()

    elif event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer", "")
        result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
        user = result.scalar_one_or_none()
        if user is not None:
            await send_payment_failed_email(user.email)
