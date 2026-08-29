"""Tests for the hosted monthly generation allowance.

The contract, from the model-tier design note: Sonnet 5 is the default, Opus 5
is chosen per job, and hosted users get 15 Opus generations and 150 in total
per calendar month. When the Opus allowance is spent the proxy quietly swaps in
the fallback model and says so in the response; when the total cap is reached
it refuses with a 429 naming the reset date. Nothing is counted unless
Anthropic returned a 200.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models import GenerationUsage
from app.routes.proxy import proxy_allowance, proxy_generate, proxy_generate_stream
from app.services import allowance

_TOKEN = "cp-abcd1234efgh"
_USER_ID = 1
_OPUS = "claude-opus-5"
_SONNET = "claude-sonnet-5"


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _async_ctx(value) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = _async_return(value)
    ctx.__aexit__ = _async_return(False)
    return ctx


def _request(model: str = _SONNET) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_async_return({"model": model, "messages": []}),
    )


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=_USER_ID, subscription_status="active")


def _patch_lookup():
    return patch("app.routes.proxy._get_user_by_cp_token", _async_return(_user()))


def _patch_sessions(factory):
    return patch("app.routes.proxy.get_session_factory", lambda: factory)


class _FakeJsonResponse:
    """Minimal stand-in for a non-streaming httpx response."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


_ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "#!/bin/bash\n"}],
    "usage": {"input_tokens": 1200, "output_tokens": 480},
}


class _FakePost:
    """Patch httpx.AsyncClient in the proxy module for the non-streaming route."""

    def __init__(self, response: _FakeJsonResponse) -> None:
        self.client = MagicMock()
        self.client.post = MagicMock(side_effect=_async_return(response))
        self._patcher = patch(
            "app.routes.proxy.httpx.AsyncClient",
            MagicMock(return_value=_async_ctx(self.client)),
        )

    def __enter__(self) -> _FakePost:
        self._patcher.start()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self._patcher.stop()
        return False

    @property
    def sent_payload(self) -> dict:
        return self.client.post.call_args.kwargs["json"]


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str], body: bytes = b"") -> None:
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


class _FakeStream:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self.client = MagicMock()
        self.client.stream = MagicMock(return_value=_async_ctx(response))
        self._patcher = patch(
            "app.routes.proxy.httpx.AsyncClient",
            MagicMock(return_value=_async_ctx(self.client)),
        )

    def __enter__(self) -> _FakeStream:
        self._patcher.start()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self._patcher.stop()
        return False

    @property
    def sent_payload(self) -> dict:
        return self.client.stream.call_args.kwargs["json"]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}"


_STREAM_LINES = [
    _sse({"type": "message_start",
          "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}}),
    _sse({"type": "content_block_delta",
          "delta": {"type": "text_delta", "text": "#!/bin/bash\n"}}),
    _sse({"type": "message_delta",
          "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 20}}),
]


async def _collect(response) -> list[dict]:
    chunks = [chunk async for chunk in response.body_iterator]
    text = b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode("utf-8") for chunk in chunks
    ).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


async def _seed(db, month: str, total: int, opus: int) -> None:
    db.add(GenerationUsage(user_id=_USER_ID, month=month, total=total, opus=opus))
    await db.commit()


async def _rows(db) -> list[GenerationUsage]:
    result = await db.execute(
        select(GenerationUsage).order_by(GenerationUsage.month)
    )
    return list(result.scalars().all())


def _body(response) -> dict:
    return json.loads(bytes(response.body).decode("utf-8"))


class TestMonthArithmetic:
    def test_current_month_is_utc_and_yyyy_mm(self):
        from datetime import datetime, timezone

        moment = datetime(2026, 8, 28, 23, 55, tzinfo=timezone.utc)
        assert allowance.current_month(moment) == "2026-08"

    @pytest.mark.parametrize(
        "month,expected",
        [("2026-08", "2026-09-01"), ("2026-12", "2027-01-01"), ("2026-01", "2026-02-01")],
    )
    def test_resets_on_is_the_first_of_the_next_month(self, month: str, expected: str):
        assert allowance.resets_on(month) == expected

    def test_only_opus_model_names_count_as_opus(self):
        assert allowance.is_opus("claude-opus-5") is True
        assert allowance.is_opus("claude-opus-4-6") is True
        assert allowance.is_opus("claude-sonnet-5") is False
        assert allowance.is_opus("") is False


class TestTotalCap:
    async def test_at_the_cap_the_route_refuses_with_429(self, db, db_factory):
        month = allowance.current_month()
        await _seed(db, month, total=settings.total_monthly_cap, opus=0)

        with _patch_lookup(), _FakePost(_FakeJsonResponse(200, _ANTHROPIC_OK)):
            with pytest.raises(HTTPException) as excinfo:
                await proxy_generate(_request(), db=db)

        assert excinfo.value.status_code == 429
        assert excinfo.value.detail == (
            f"Monthly generation allowance of {settings.total_monthly_cap} "
            f"reached; it resets on {allowance.resets_on(month)}."
        )

    async def test_the_cap_names_the_reset_date(self, db):
        await _seed(db, allowance.current_month(), total=settings.total_monthly_cap, opus=0)
        with pytest.raises(HTTPException) as excinfo:
            await allowance.check_and_prepare(db, _user(), {"model": _SONNET})
        assert allowance.resets_on(allowance.current_month()) in excinfo.value.detail

    async def test_one_below_the_cap_is_allowed(self, db):
        await _seed(db, allowance.current_month(), total=settings.total_monthly_cap - 1, opus=0)
        prepared = await allowance.check_and_prepare(db, _user(), {"model": _SONNET})
        assert prepared.fallback is False

    async def test_the_cap_refuses_before_any_upstream_call(self, db, db_factory):
        await _seed(db, allowance.current_month(), total=settings.total_monthly_cap, opus=0)

        with _patch_lookup(), _patch_sessions(db_factory), _FakeStream(
            _FakeStreamResponse(200, _STREAM_LINES)
        ) as upstream:
            with pytest.raises(HTTPException):
                await proxy_generate_stream(_request(_OPUS), db=db)
            assert upstream.client.stream.call_count == 0


class TestOpusFallback:
    async def test_beyond_the_allowance_opus_is_served_by_the_fallback(self, db, db_factory):
        await _seed(db, allowance.current_month(), total=20,
                    opus=settings.opus_monthly_allowance)

        with _patch_lookup(), _FakePost(_FakeJsonResponse(200, _ANTHROPIC_OK)) as upstream:
            response = await proxy_generate(_request(_OPUS), db=db)

        # The substitution reaches Anthropic, not just the response body.
        assert upstream.sent_payload["model"] == settings.fallback_model
        body = _body(response)
        assert body["model_used"] == settings.fallback_model
        assert body["fallback"] is True

        # A fallback generation costs a total, never an Opus.
        rows = await _rows(db)
        assert (rows[0].total, rows[0].opus) == (21, settings.opus_monthly_allowance)

    async def test_within_the_allowance_opus_is_served_as_opus(self, db, db_factory):
        await _seed(db, allowance.current_month(), total=3, opus=2)

        with _patch_lookup(), _FakePost(_FakeJsonResponse(200, _ANTHROPIC_OK)) as upstream:
            response = await proxy_generate(_request(_OPUS), db=db)

        assert upstream.sent_payload["model"] == _OPUS
        body = _body(response)
        assert body["model_used"] == _OPUS
        assert body["fallback"] is False
        assert body["remaining_opus"] == settings.opus_monthly_allowance - 3
        assert body["remaining_total"] == settings.total_monthly_cap - 4

        rows = await _rows(db)
        assert (rows[0].total, rows[0].opus) == (4, 3)

    async def test_a_sonnet_request_never_touches_the_opus_count(self, db, db_factory):
        with _patch_lookup(), _FakePost(_FakeJsonResponse(200, _ANTHROPIC_OK)):
            response = await proxy_generate(_request(_SONNET), db=db)

        body = _body(response)
        assert body["model_used"] == _SONNET
        assert body["fallback"] is False

        rows = await _rows(db)
        assert (rows[0].total, rows[0].opus) == (1, 0)

    async def test_the_fallback_is_reported_on_the_stream_done_line(self, db, db_factory):
        await _seed(db, allowance.current_month(), total=20,
                    opus=settings.opus_monthly_allowance)

        with _patch_lookup(), _patch_sessions(db_factory), _FakeStream(
            _FakeStreamResponse(200, _STREAM_LINES)
        ) as upstream:
            response = await proxy_generate_stream(_request(_OPUS), db=db)
            records = await _collect(response)

        assert upstream.sent_payload["model"] == settings.fallback_model
        done = records[-1]
        assert done["done"] is True
        assert done["model_used"] == settings.fallback_model
        assert done["fallback"] is True
        assert done["remaining_opus"] == 0
        assert done["remaining_total"] == settings.total_monthly_cap - 21


class TestCountingOnSuccessOnly:
    async def test_an_anthropic_500_counts_nothing(self, db, db_factory):
        with _patch_lookup(), _FakePost(_FakeJsonResponse(500, {"error": "boom"})):
            with pytest.raises(HTTPException) as excinfo:
                await proxy_generate(_request(_OPUS), db=db)

        assert excinfo.value.status_code == 500
        assert await _rows(db) == []

    async def test_a_stream_that_ends_in_an_error_counts_nothing(self, db, db_factory):
        with _patch_lookup(), _patch_sessions(db_factory), _FakeStream(
            _FakeStreamResponse(500, [], body=b"internal_error")
        ):
            response = await proxy_generate_stream(_request(_OPUS), db=db)
            records = await _collect(response)

        assert "500" in records[0]["error"]
        assert await _rows(db) == []

    async def test_a_successful_stream_counts_once(self, db, db_factory):
        with _patch_lookup(), _patch_sessions(db_factory), _FakeStream(
            _FakeStreamResponse(200, _STREAM_LINES)
        ):
            response = await proxy_generate_stream(_request(_OPUS), db=db)
            await _collect(response)

        rows = await _rows(db)
        assert (rows[0].total, rows[0].opus) == (1, 1)


class TestMonthRollover:
    async def test_a_new_month_starts_a_fresh_row(self, db):
        await _seed(db, "2026-08", total=settings.total_monthly_cap, opus=15)

        with patch("app.services.allowance.current_month", lambda *a: "2026-09"):
            # August was at the cap; September is not.
            prepared = await allowance.check_and_prepare(db, _user(), {"model": _OPUS})
            assert prepared.fallback is False
            assert prepared.month == "2026-09"
            counts = await allowance.record_success(db, _USER_ID, _OPUS)

        assert (counts.total, counts.opus) == (1, 1)

        rows = await _rows(db)
        assert [(row.month, row.total, row.opus) for row in rows] == [
            ("2026-08", settings.total_monthly_cap, 15),
            ("2026-09", 1, 1),
        ]

    async def test_a_month_with_no_row_reads_as_zero(self, db):
        usage = await allowance.get_usage(db, _USER_ID, "2027-03")
        assert (usage.month, usage.total, usage.opus) == ("2027-03", 0, 0)


class TestAllowanceRoute:
    async def test_returns_the_documented_shape(self, db):
        month = allowance.current_month()
        await _seed(db, month, total=41, opus=3)

        with _patch_lookup():
            response = await proxy_allowance(_request(), db=db)

        assert _body(response) == {
            "month": month,
            "opus_used": 3,
            "opus_limit": settings.opus_monthly_allowance,
            "total_used": 41,
            "total_limit": settings.total_monthly_cap,
            "fallback_model": settings.fallback_model,
            "resets_on": allowance.resets_on(month),
        }

    async def test_a_user_with_no_usage_reads_as_zero(self, db):
        with _patch_lookup():
            response = await proxy_allowance(_request(), db=db)

        body = _body(response)
        assert body["opus_used"] == 0
        assert body["total_used"] == 0

    async def test_the_subscription_gate_applies(self, db):
        unsubscribed = SimpleNamespace(id=_USER_ID, subscription_status="canceled")
        with patch("app.routes.proxy._get_user_by_cp_token", _async_return(unsubscribed)):
            with pytest.raises(HTTPException) as excinfo:
                await proxy_allowance(_request(), db=db)
        assert excinfo.value.status_code == 402
