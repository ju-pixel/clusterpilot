from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_current_user, get_db
from app.models import User
from app.schemas import UserOut
from app.services.stripe import create_checkout_session, create_customer_portal_session, get_or_create_customer

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a Stripe Checkout Session for a new subscription (14-day trial)."""
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
        price_id=settings.stripe_price_id_monthly,
        success_url="https://app.clusterpilot.sh?subscribed=1",
        cancel_url="https://app.clusterpilot.sh",
        trial_period_days=14,
    )
    return {"url": url}
