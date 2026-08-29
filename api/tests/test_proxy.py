"""Tests for the managed-key proxy routes.

Two contracts are pinned here.

Issue #4: the subscription gate accepted only the literal "active", but Stripe
writes "trialing" for the whole 14-day trial, so a trialing subscriber got a
402 from the managed key. The gate now uses ``SUBSCRIBED_STATUSES``.

Issue #41: /proxy/generate-stream turns Anthropic's SSE into newline-delimited
JSON, one object per line, because Fly.io buffers text/event-stream and the
hosted tier therefore could not stream at all.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models import SUBSCRIBED_STATUSES
from app.routes.proxy import _authorised_user, proxy_generate_stream

_TOKEN = "cp-abcd1234efgh"


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _async_ctx(value) -> MagicMock:
    """An object usable as ``async with`` that yields ``value``."""
    ctx = MagicMock()
    ctx.__aenter__ = _async_return(value)
    ctx.__aexit__ = _async_return(False)
    return ctx


def _request(payload: dict | None = None) -> SimpleNamespace:
    """A stand-in for starlette's Request with just what the routes touch."""
    return SimpleNamespace(
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_async_return(payload if payload is not None else {"model": "claude-sonnet-4-6"}),
    )


def _user(status: str) -> SimpleNamespace:
    return SimpleNamespace(id=1, subscription_status=status)


def _patch_lookup(user: SimpleNamespace):
    return patch("app.routes.proxy._get_user_by_cp_token", _async_return(user))


class _FakeStreamResponse:
    """Minimal stand-in for an httpx streaming response."""

    def __init__(self, status_code: int, lines: list[str], body: bytes = b"") -> None:
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


class _FakeAnthropic:
    """Patch httpx.AsyncClient in the proxy module and record the call made."""

    def __init__(self, response: _FakeStreamResponse) -> None:
        self.client = MagicMock()
        self.client.stream = MagicMock(return_value=_async_ctx(response))
        self._patcher = patch(
            "app.routes.proxy.httpx.AsyncClient",
            MagicMock(return_value=_async_ctx(self.client)),
        )
        self.constructor: MagicMock | None = None

    def __enter__(self) -> _FakeAnthropic:
        self.constructor = self._patcher.start()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self._patcher.stop()
        return False

    @property
    def was_called(self) -> bool:
        assert self.constructor is not None
        return self.constructor.call_count > 0

    @property
    def sent_payload(self) -> dict:
        return self.client.stream.call_args.kwargs["json"]


async def _collect(response) -> list[dict]:
    """Drain a StreamingResponse into the JSON records it emitted."""
    chunks = [chunk async for chunk in response.body_iterator]
    text = b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode("utf-8") for chunk in chunks
    ).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}"


_STREAM_LINES = [
    "event: message_start",
    _sse({"type": "message_start",
          "message": {"usage": {"input_tokens": 1200, "output_tokens": 1}}}),
    "",
    _sse({"type": "content_block_delta",
          "delta": {"type": "text_delta", "text": "#!/bin/bash\n"}}),
    _sse({"type": "content_block_delta",
          "delta": {"type": "text_delta", "text": "#SBATCH --time=01:00:00\n"}}),
    _sse({"type": "ping"}),
    _sse({"type": "message_delta",
          "delta": {"stop_reason": "end_turn"},
          "usage": {"output_tokens": 480}}),
    "data: [DONE]",
]


class TestSubscriptionGate:
    def test_trialing_is_a_subscribed_status(self):
        # Stripe writes its own literal, and the trial one is "trialing".
        assert SUBSCRIBED_STATUSES == frozenset({"active", "trialing"})

    @pytest.mark.parametrize("status", ["active", "trialing"])
    async def test_subscribed_statuses_pass(self, status: str):
        with _patch_lookup(_user(status)):
            user = await _authorised_user(_request(), db=object())
        assert user.subscription_status == status

    @pytest.mark.parametrize("status", ["canceled", "cancelled", "past_due", "free"])
    async def test_unsubscribed_statuses_are_refused(self, status: str):
        with _patch_lookup(_user(status)):
            with pytest.raises(HTTPException) as excinfo:
                await _authorised_user(_request(), db=object())
        assert excinfo.value.status_code == 402

    async def test_missing_token_is_a_401(self):
        request = SimpleNamespace(headers={}, json=_async_return({}))
        with pytest.raises(HTTPException) as excinfo:
            await _authorised_user(request, db=object())
        assert excinfo.value.status_code == 401


class TestGenerateStream:
    async def test_yields_ndjson_deltas_then_a_done_record(self):
        with _patch_lookup(_user("trialing")), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ):
            response = await proxy_generate_stream(_request(), db=object())
            records = await _collect(response)

        assert records == [
            {"text": "#!/bin/bash\n"},
            {"text": "#SBATCH --time=01:00:00\n"},
            {"done": True, "stop_reason": "end_turn",
             "input_tokens": 1200, "output_tokens": 480},
        ]

    async def test_response_is_unbuffered_ndjson(self):
        with _patch_lookup(_user("active")), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ):
            response = await proxy_generate_stream(_request(), db=object())

        # Not text/event-stream: Fly.io buffers that, which is issue #41.
        assert response.media_type == "application/x-ndjson"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-cache"

    async def test_forces_streaming_on_the_upstream_payload(self):
        request = _request({"model": "claude-sonnet-4-6", "stream": False})
        with _patch_lookup(_user("active")), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ) as upstream:
            response = await proxy_generate_stream(request, db=object())
            await _collect(response)
            assert upstream.sent_payload["stream"] is True

    async def test_upstream_error_becomes_a_single_error_record(self):
        with _patch_lookup(_user("active")), _FakeAnthropic(
            _FakeStreamResponse(529, [], body=b"overloaded_error")
        ):
            response = await proxy_generate_stream(_request(), db=object())
            records = await _collect(response)

        assert len(records) == 1
        assert "529" in records[0]["error"]
        assert "done" not in records[0]

    async def test_error_event_mid_stream_ends_the_stream(self):
        lines = [
            _sse({"type": "content_block_delta",
                  "delta": {"type": "text_delta", "text": "partial"}}),
            _sse({"type": "error", "error": {"type": "overloaded_error"}}),
        ]
        with _patch_lookup(_user("active")), _FakeAnthropic(
            _FakeStreamResponse(200, lines)
        ):
            response = await proxy_generate_stream(_request(), db=object())
            records = await _collect(response)

        assert records[0] == {"text": "partial"}
        assert "overloaded_error" in records[1]["error"]
        assert len(records) == 2

    async def test_gate_runs_before_any_upstream_call(self):
        with _patch_lookup(_user("free")), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ) as upstream:
            with pytest.raises(HTTPException) as excinfo:
                await proxy_generate_stream(_request(), db=object())
            assert excinfo.value.status_code == 402
            assert upstream.was_called is False
