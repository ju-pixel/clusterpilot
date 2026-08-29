from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_current_user, get_db
from app.models import User
from app.schemas import CheckoutRequest, PICheckoutRequest, SubscriptionOut, UserOut
from app.services.stripe import (
    create_checkout_session,
    create_customer_portal_session,
    get_or_create_customer,
    get_subscription_summary,
)

router = APIRouter(prefix="/users", tags=["users"])


def _price_id_for(interval: str) -> str:
    """The Stripe price for a billing interval; anything but ``year`` is monthly."""
    if interval == "year":
        return settings.stripe_price_id_annual
    return settings.stripe_price_id_monthly


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/me/subscription", response_model=Optional[SubscriptionOut])
async def get_subscription(
    current_user: User = Depends(get_current_user),
) -> Optional[SubscriptionOut]:
    """The plan the user is on, or null for a sponsored seat or no subscription."""
    if not current_user.stripe_customer_id:
        return None
    return await get_subscription_summary(current_user.stripe_customer_id)


@router.post("/me/billing-portal")
async def billing_portal(
    current_user: User = Depends(get_current_user),
) -> dict:
    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No billing account found for this user.",
        )
    url = await create_customer_portal_session(
        customer_id=current_user.stripe_customer_id,
        return_url="https://app.clusterpilot.sh",
    )
    return {"url": url}


@router.post("/me/checkout")
async def create_checkout(
    body: Optional[CheckoutRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a Stripe Checkout Session for a new subscription (14-day trial).

    The body is optional: a dashboard that predates the annual option sends
    none and gets the monthly price.
    """
    interval = body.interval if body is not None else "month"
    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer_id = await get_or_create_customer(
            email=current_user.email,
            clerk_id=current_user.clerk_id,
        )
        current_user.stripe_customer_id = customer_id
        await db.commit()

    url = await create_checkout_session(
        customer_id=customer_id,
        price_id=_price_id_for(interval),
        success_url="https://app.clusterpilot.sh?subscribed=1",
        cancel_url="https://app.clusterpilot.sh",
        trial_period_days=14,
    )
    return {"url": url}


@router.post("/me/checkout-pi")
async def create_pi_checkout(
    body: PICheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a Stripe Checkout Session for a PI group bundle (min 3 seats, 15% off).

    The bundle takes the same monthly or yearly price as a researcher seat;
    the 15% comes from the group coupon, which is permanent (duration
    ``forever`` in Stripe) so yearly renewals keep it.
    """
    if body.quantity < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum quantity for a group bundle is 3 seats.",
        )

    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer_id = await get_or_create_customer(
            email=current_user.email,
            clerk_id=current_user.clerk_id,
        )
        current_user.stripe_customer_id = customer_id
        await db.commit()

    url = await create_checkout_session(
        customer_id=customer_id,
        price_id=_price_id_for(body.interval),
        success_url="https://app.clusterpilot.sh?subscribed=1",
        cancel_url="https://app.clusterpilot.sh",
        is_pi_group=True,
        quantity=body.quantity,
    )
    return {"url": url}
