"""Stripe SDK wrappers."""

from typing import Optional

import stripe
from fastapi import HTTPException, status

from app.config import settings
from app.schemas import SubscriptionOut

stripe.api_key = settings.stripe_secret_key


async def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    is_pi_group: bool = False,
    quantity: int = 1,
    trial_period_days: int = 0,
) -> str:
    """Create a Stripe Checkout Session and return the redirect URL."""
    params: dict = {
        "customer": customer_id,
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": quantity}],
        "success_url": success_url,
        "cancel_url": cancel_url,
    }

    if trial_period_days > 0:
        params["subscription_data"] = {"trial_period_days": trial_period_days}

    if is_pi_group:
        params["line_items"][0]["adjustable_quantity"] = {
            "enabled": True,
            "minimum": 3,
        }
        params["discounts"] = [{"coupon": settings.stripe_coupon_pi_group}]
        params["metadata"] = {"type": "pi_bundle", "quantity": str(quantity)}

    session = stripe.checkout.Session.create(**params)
    return session.url  # type: ignore[return-value]


async def create_customer_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session and return the redirect URL."""
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url  # type: ignore[return-value]


async def get_subscription_summary(customer_id: str) -> Optional[SubscriptionOut]:
    """The customer's live subscription as the dashboard shows it, or None.

    Stripe lists a customer's uncancelled subscriptions newest first, and a
    ClusterPilot customer only ever holds one. It is read live rather than
    stored so the price shown is the one Stripe will actually charge,
    founding lock included.
    """
    subs = stripe.Subscription.list(customer=customer_id, limit=1)
    if not subs.data:
        return None
    sub = subs.data[0]
    item = sub["items"]["data"][0]
    price = item["price"]
    return SubscriptionOut(
        interval=price["recurring"]["interval"],
        amount=price["unit_amount"] or 0,
        currency=price["currency"],
        quantity=item.get("quantity") or 1,
        status=sub["status"],
    )


async def get_or_create_customer(email: str, clerk_id: str) -> str:
    """Look up a Stripe customer by metadata or create one."""
    existing = stripe.Customer.search(
        query=f'metadata["clerk_id"]:"{clerk_id}"',
        limit=1,
    )
    if existing.data:
        return existing.data[0].id  # type: ignore[return-value]

    customer = stripe.Customer.create(
        email=email,
        metadata={"clerk_id": clerk_id},
    )
    return customer.id  # type: ignore[return-value]


def construct_stripe_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify Stripe webhook signature and return the parsed event."""
    try:
        return stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Stripe webhook: {exc}",
        ) from exc
