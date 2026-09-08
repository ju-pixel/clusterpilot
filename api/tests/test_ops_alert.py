"""Tests for the operator alert (issue #61).

The alert exists so that a revoked master key or an empty Anthropic account is
noticed by the operator rather than reported by a subscriber. What is pinned
here is the shape of that promise: only the two failures that mean everyone is
broken, one push per status code per ten minutes, nothing at all when the
secret is unset, and never an exception on the request path.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.services import ops_alert

_CREDIT_BODY = (
    '{"type":"error","error":{"type":"invalid_request_error",'
    '"message":"Your credit balance is too low to access the Anthropic API."}}'
)


@pytest.fixture(autouse=True)
def _clean_state():
    """A configured endpoint and an empty rate-limit table for every test."""
    ops_alert._last_sent.clear()
    previous = settings.ops_ntfy_url
    settings.ops_ntfy_url = "https://ntfy.sh/cp-ops-test"
    yield
    settings.ops_ntfy_url = previous
    ops_alert._last_sent.clear()


class TestIsAlertable:
    @pytest.mark.parametrize("body", ["", "invalid x-api-key"])
    def test_a_401_is_always_alertable(self, body: str):
        # The master key is revoked, rotated or mistyped: nobody can generate.
        assert ops_alert.is_alertable(401, body) is True

    def test_a_400_naming_the_credit_balance_is_alertable(self):
        assert ops_alert.is_alertable(400, _CREDIT_BODY) is True

    def test_the_credit_balance_match_ignores_case(self):
        assert ops_alert.is_alertable(400, "CREDIT BALANCE too low") is True

    @pytest.mark.parametrize(
        "status_code,body",
        [
            (400, '{"error":{"message":"max_tokens: must be >= 1"}}'),
            (429, "rate limited"),
            (500, "internal server error"),
            (529, "overloaded_error"),
        ],
    )
    def test_transient_or_per_request_failures_are_not_alertable(
        self, status_code: int, body: str
    ):
        # Paging on these would train the operator to ignore the topic.
        assert ops_alert.is_alertable(status_code, body) is False


class TestClaimAlert:
    def test_returns_the_route_status_and_body_prefix(self):
        message = ops_alert.claim_alert("/proxy/generate", 401, "invalid x-api-key")
        assert message is not None
        assert "/proxy/generate" in message
        assert "401" in message
        assert "invalid x-api-key" in message

    def test_the_body_is_trimmed(self):
        message = ops_alert.claim_alert("/proxy/generate", 401, "x" * 500)
        assert message is not None
        # A push is one line, so the body is a prefix, not the whole document.
        assert message.endswith(": " + "x" * 120)

    def test_nothing_is_claimed_when_the_setting_is_empty(self):
        settings.ops_ntfy_url = ""
        assert ops_alert.claim_alert("/proxy/generate", 401, "invalid x-api-key") is None
        assert ops_alert._last_sent == {}

    def test_one_push_per_status_code_per_ten_minutes(self):
        first = ops_alert.claim_alert("/proxy/generate", 401, "invalid", now=0.0)
        second = ops_alert.claim_alert("/proxy/generate", 401, "invalid", now=599.0)
        third = ops_alert.claim_alert("/proxy/generate", 401, "invalid", now=601.0)

        assert first is not None
        assert second is None      # 150 identical failures are still one push
        assert third is not None   # the window has passed

    def test_the_window_is_kept_per_status_code(self):
        assert ops_alert.claim_alert("/proxy/generate", 401, "invalid", now=0.0)
        # A different outage inside the same window still gets its own push.
        assert ops_alert.claim_alert("/proxy/generate", 400, _CREDIT_BODY, now=1.0)


class TestMaybeAlert:
    async def test_schedules_the_post_without_awaiting_it(self):
        sent: list[str] = []

        async def _record(message: str) -> None:
            sent.append(message)

        with patch.object(ops_alert, "_post", _record):
            ops_alert.maybe_alert("/proxy/v1/messages", 401, "invalid x-api-key")
            assert sent == []  # nothing has run yet: the response is not delayed
            await asyncio.gather(*list(ops_alert._background))

        assert len(sent) == 1
        assert "/proxy/v1/messages" in sent[0]

    async def test_nothing_is_scheduled_for_an_uninteresting_failure(self):
        with patch.object(ops_alert, "_post", MagicMock()) as post:
            ops_alert.maybe_alert("/proxy/generate", 529, "overloaded_error")
        assert post.call_count == 0

    async def test_a_dead_endpoint_never_raises(self):
        """The POST swallows everything: an alert must not create a second fault."""

        def _explode(*args: object, **kwargs: object):
            raise httpx.ConnectError("ntfy.sh is unreachable")

        with patch.object(httpx, "AsyncClient", _explode):
            await ops_alert._post("anything")
