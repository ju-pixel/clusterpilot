"""Tests for the hosted-tier checkout routes and the plan readout.

The annual option (2026-08-28): ``POST /users/me/checkout`` takes an optional
``{"interval": "month" | "year"}`` body and picks the matching Stripe price.
The body is optional so a dashboard built before the option existed keeps
working and gets monthly. Group seat bundles take the same interval, monthly
by default, with the 15% group coupon on top. ``GET /users/me/subscription``
reads the plan live from Stripe so the Account page never hard-codes a price.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import settings
from app.routes.users import create_checkout, create_pi_checkout, get_subscription
from app.schemas import CheckoutRequest, PICheckoutRequest
from app.services import stripe as stripe_service

_URL = "https://checkout.stripe.com/c/pay/test"


def _user(customer: Optional[str] = "cus_test") -> SimpleNamespace:
    return SimpleNamespace(
        id=1, email="x@example.org", clerk_id="user_1", stripe_customer_id=customer,
    )


def _capture_session():
    """Patch the checkout session factory; returns (patcher, kwargs it received)."""
    calls: list[dict] = []

    async def _fake(**kwargs):
        calls.append(kwargs)
        return _URL

    return patch("app.routes.users.create_checkout_session", _fake), calls


def _stripe_subscription(
    interval: str, amount: int, quantity: int = 1, status: str = "trialing",
) -> dict:
    """The slice of a Stripe Subscription object that the summary reads."""
    return {
        "status": status,
        "items": {"data": [{
            "quantity": quantity,
            "price": {
                "unit_amount": amount,
                "currency": "usd",
                "recurring": {"interval": interval},
            },
        }]},
    }


def _patch_stripe_list(subscriptions: list[dict]):
    return patch.object(
        stripe_service.stripe.Subscription, "list",
        return_value=SimpleNamespace(data=subscriptions),
    )


class TestCheckoutInterval:
    async def test_no_body_is_monthly(self):
        patcher, calls = _capture_session()
        with patcher:
            out = await create_checkout(body=None, current_user=_user(), db=None)
        assert out == {"url": _URL}
        assert calls[0]["price_id"] == settings.stripe_price_id_monthly

    async def test_month_is_monthly(self):
        patcher, calls = _capture_session()
        with patcher:
            await create_checkout(
                body=CheckoutRequest(interval="month"), current_user=_user(), db=None,
            )
        assert calls[0]["price_id"] == settings.stripe_price_id_monthly

    async def test_year_is_annual_with_the_same_trial(self):
        patcher, calls = _capture_session()
        with patcher:
            await create_checkout(
                body=CheckoutRequest(interval="year"), current_user=_user(), db=None,
            )
        assert calls[0]["price_id"] == settings.stripe_price_id_annual
        assert calls[0]["trial_period_days"] == 14

    def test_other_intervals_are_rejected(self):
        with pytest.raises(ValidationError):
            CheckoutRequest(interval="week")

    def test_default_interval_is_month(self):
        assert CheckoutRequest().interval == "month"

    async def test_group_bundle_defaults_to_monthly(self):
        patcher, calls = _capture_session()
        with patcher:
            await create_pi_checkout(
                body=PICheckoutRequest(quantity=3), current_user=_user(), db=None,
            )
        assert calls[0]["price_id"] == settings.stripe_price_id_monthly
        assert calls[0]["is_pi_group"] is True
        assert calls[0]["quantity"] == 3

    async def test_group_bundle_year_is_annual_with_the_discount(self):
        patcher, calls = _capture_session()
        with patcher:
            await create_pi_checkout(
                body=PICheckoutRequest(quantity=4, interval="year"),
                current_user=_user(), db=None,
            )
        assert calls[0]["price_id"] == settings.stripe_price_id_annual
        assert calls[0]["is_pi_group"] is True
        assert calls[0]["quantity"] == 4

    def test_group_bundle_rejects_other_intervals(self):
        with pytest.raises(ValidationError):
            PICheckoutRequest(quantity=3, interval="week")


class TestSubscriptionReadout:
    async def test_annual_plan(self):
        with _patch_stripe_list([_stripe_subscription("year", 6000)]):
            out = await get_subscription(current_user=_user())
        assert out is not None
        assert (out.interval, out.amount, out.currency, out.quantity, out.status) == (
            "year", 6000, "usd", 1, "trialing",
        )

    async def test_monthly_plan(self):
        with _patch_stripe_list([_stripe_subscription("month", 600, status="active")]):
            out = await get_subscription(current_user=_user())
        assert (out.interval, out.amount, out.status) == ("month", 600, "active")

    async def test_group_bundle_reports_seats(self):
        with _patch_stripe_list([_stripe_subscription("month", 600, quantity=3, status="active")]):
            out = await get_subscription(current_user=_user())
        assert out.quantity == 3

    async def test_no_customer_is_null_without_calling_stripe(self):
        with _patch_stripe_list([]) as listed:
            assert await get_subscription(current_user=_user(customer=None)) is None
        listed.assert_not_called()

    async def test_no_subscription_is_null(self):
        with _patch_stripe_list([]) as listed:
            assert await get_subscription(current_user=_user()) is None
        listed.assert_called_once_with(customer="cus_test", limit=1)
