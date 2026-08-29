"""Test settings for the hosted API.

``app.config.Settings`` has required fields and is instantiated at import time,
so every value it needs must be in the environment before any ``app.*`` module
is imported. conftest is imported before the test modules, which makes this the
right place for it. None of these are real credentials.
"""
from __future__ import annotations

import os

_TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "CLERK_SECRET_KEY": "sk_test_not_a_real_key",
    "CLERK_WEBHOOK_SECRET": "whsec_test_not_a_real_secret",
    "STRIPE_SECRET_KEY": "sk_test_not_a_real_key",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_not_a_real_secret",
    "STRIPE_PRICE_ID_MONTHLY": "price_test_monthly",
    "STRIPE_PRICE_ID_ANNUAL": "price_test_annual",
    "RESEND_API_KEY": "re_test_not_a_real_key",
    "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
    "ENVIRONMENT": "test",
}

for _name, _value in _TEST_ENV.items():
    os.environ.setdefault(_name, _value)
