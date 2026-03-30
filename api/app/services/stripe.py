"""Stripe SDK wrappers."""

import stripe
from fastapi import HTTPException, status

from app.config import settings

stripe.api_key = settings.stripe_secret_key


async def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    is_pi_group: bool = False,
    quantity: int = 1,
) -> str:
    """Create a Stripe Checkout Session and return the redirect URL."""
    params: dict = {
        "customer": customer_id,
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": quantity}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": False,
    }

    if is_pi_group:
        params["line_items"][0]["adjustable_quantity"] = {
            "enabled": True,
            "minimum": 3,
        }
        params["discounts"] = [{"coupon": settings.stripe_coupon_pi_group}]

    session = stripe.checkout.Session.create(**params)
    return session.url  # type: ignore[return-value]


async def create_customer_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session and return the redirect URL."""
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url  # type: ignore[return-value]


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
