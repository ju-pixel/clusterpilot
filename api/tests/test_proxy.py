"""Tests for the managed-key proxy routes.

Two contracts are pinned here.

Issue #4: the subscription gate accepted only the literal "active", but Stripe
writes "trialing" for the whole 14-day trial, so a trialing subscriber got a
402 from the managed key. The gate now uses ``SUBSCRIBED_STATUSES``.

Issue #41: /proxy/generate-stream turns Anthropic's SSE into newline-delimited
JSON, one object per line, because Fly.io buffers text/event-stream and the
hosted tier therefore could not stream at all.

Issue #61: an upstream failure is ours, not the caller's. All three routes now
log the status and body server-side and return one fixed service message, so a
revoked master key or an empty billing account can never read to a subscriber
as a problem with their subscription or their allowance.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.config import settings
from app.models import SUBSCRIBED_STATUSES
from app.routes.proxy import (
    _SERVICE_UNAVAILABLE,
    _authorised_user,
    proxy_generate,
    proxy_generate_stream,
    proxy_messages,
)
from app.services import ops_alert

_TOKEN = "cp-abcd1234efgh"

# The two upstream bodies that mean the hosted tier is down for everyone.
_CREDIT_BODY = (
    '{"type":"error","error":{"type":"invalid_request_error",'
    '"message":"Your credit balance is too low to access the Anthropic API."}}'
)
_AUTH_BODY = (
    '{"type":"error","error":{"type":"authentication_error",'
    '"message":"invalid x-api-key"}}'
)


@pytest.fixture(autouse=True)
async def _quiet_ops_alert():
    """No operator pushes by default, and no rate-limit state carried between tests."""
    ops_alert._last_sent.clear()
    previous = settings.ops_ntfy_url
    settings.ops_ntfy_url = ""
    yield
    # Drain anything a failing assertion left scheduled, or the next test sees a
    # "Task was destroyed but it is pending" warning that reads like a leak.
    await _drain_alerts()
    settings.ops_ntfy_url = previous
    ops_alert._last_sent.clear()


async def _drain_alerts() -> None:
    """Wait for any scheduled operator push to finish before asserting on it."""
    if ops_alert._background:
        await asyncio.gather(*list(ops_alert._background))


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
    body = payload if payload is not None else {"model": "claude-sonnet-4-6"}
    return SimpleNamespace(
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_async_return(body),
        body=_async_return(json.dumps(body).encode("utf-8")),
    )


def _user(status: str) -> SimpleNamespace:
    return SimpleNamespace(id=1, subscription_status=status)


def _patch_lookup(user: SimpleNamespace):
    return patch("app.routes.proxy._get_user_by_cp_token", _async_return(user))


def _patch_sessions(factory):
    """Point the stream generator's own session factory at the test database."""
    return patch("app.routes.proxy.get_session_factory", lambda: factory)


class _FakeStreamResponse:
    """Minimal stand-in for an httpx streaming response."""

    def __init__(
        self,
        status_code: int,
        lines: list[str],
        body: bytes = b"",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self._lines = lines
        self._body = body
        self._chunks = chunks or []

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return self._body


class _FakeJsonResponse:
    """Minimal stand-in for a non-streaming httpx response."""

    def __init__(self, status_code: int, text: str = "", data: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._data = data or {}

    def json(self) -> dict:
        return self._data


class _FakeAnthropic:
    """Patch httpx.AsyncClient in the proxy module and record the call made."""

    def __init__(
        self,
        response: _FakeStreamResponse | None = None,
        post: _FakeJsonResponse | None = None,
    ) -> None:
        self.client = MagicMock()
        if response is not None:
            self.client.stream = MagicMock(return_value=_async_ctx(response))
        if post is not None:
            self.client.post = _async_return(post)
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
    async def test_yields_ndjson_deltas_then_a_done_record(self, db, db_factory):
        with _patch_lookup(_user("trialing")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ):
            response = await proxy_generate_stream(_request(), db=db)
            records = await _collect(response)

        assert records == [
            {"text": "#!/bin/bash\n"},
            {"text": "#SBATCH --time=01:00:00\n"},
            {"done": True, "stop_reason": "end_turn",
             "input_tokens": 1200, "output_tokens": 480,
             "model_used": "claude-sonnet-4-6", "fallback": False,
             "remaining_opus": 15, "remaining_total": 149},
        ]

    async def test_response_is_unbuffered_ndjson(self, db, db_factory):
        with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ):
            response = await proxy_generate_stream(_request(), db=db)

        # Not text/event-stream: Fly.io buffers that, which is issue #41.
        assert response.media_type == "application/x-ndjson"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-cache"

    async def test_forces_streaming_on_the_upstream_payload(self, db, db_factory):
        request = _request({"model": "claude-sonnet-4-6", "stream": False})
        with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ) as upstream:
            response = await proxy_generate_stream(request, db=db)
            await _collect(response)
            assert upstream.sent_payload["stream"] is True

    async def test_upstream_error_becomes_a_single_error_record(self, db, db_factory):
        with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(529, [], body=b"overloaded_error")
        ):
            response = await proxy_generate_stream(_request(), db=db)
            records = await _collect(response)

        assert len(records) == 1
        assert records[0] == {"error": _SERVICE_UNAVAILABLE}
        # Issue #61: neither the status nor Anthropic's text reaches the caller.
        assert "529" not in records[0]["error"]
        assert "overloaded_error" not in records[0]["error"]

    async def test_error_event_mid_stream_ends_the_stream(self, db, db_factory):
        lines = [
            _sse({"type": "content_block_delta",
                  "delta": {"type": "text_delta", "text": "partial"}}),
            _sse({"type": "error", "error": {"type": "overloaded_error"}}),
        ]
        with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(200, lines)
        ):
            response = await proxy_generate_stream(_request(), db=db)
            records = await _collect(response)

        assert records[0] == {"text": "partial"}
        assert "overloaded_error" in records[1]["error"]
        assert len(records) == 2

    async def test_gate_runs_before_any_upstream_call(self, db, db_factory):
        with _patch_lookup(_user("free")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(200, _STREAM_LINES)
        ) as upstream:
            with pytest.raises(HTTPException) as excinfo:
                await proxy_generate_stream(_request(), db=db)
            assert excinfo.value.status_code == 402
            assert upstream.was_called is False


class TestUpstreamFailureIsNotTheUsersFault:
    """Issue #61: an upstream 401 or an empty billing account read to the user
    as a rejected subscription. All three routes now say the same thing, tell
    the user their allowance is intact, and keep the raw body in the log."""

    @pytest.mark.parametrize(
        "status_code,body", [(400, _CREDIT_BODY), (401, _AUTH_BODY)]
    )
    async def test_generate_stream_returns_the_service_message(
        self, db, db_factory, status_code: int, body: str
    ):
        with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
            _FakeStreamResponse(status_code, [], body=body.encode("utf-8"))
        ):
            response = await proxy_generate_stream(_request(), db=db)
            records = await _collect(response)

        assert records == [{"error": _SERVICE_UNAVAILABLE}]
        assert "credit balance" not in records[0]["error"].lower()
        assert "x-api-key" not in records[0]["error"]

    @pytest.mark.parametrize(
        "status_code,body", [(400, _CREDIT_BODY), (401, _AUTH_BODY)]
    )
    async def test_generate_returns_503_with_the_service_message(
        self, db, status_code: int, body: str
    ):
        with _patch_lookup(_user("active")), _FakeAnthropic(
            post=_FakeJsonResponse(status_code, text=body)
        ):
            with pytest.raises(HTTPException) as excinfo:
                await proxy_generate(_request(), db=db)

        # 503, not the upstream status: a 401 or a 402 forwarded verbatim is
        # what the TUI read as an expired subscription.
        assert excinfo.value.status_code == 503
        assert excinfo.value.detail == _SERVICE_UNAVAILABLE
        assert "credit balance" not in excinfo.value.detail.lower()

    @pytest.mark.parametrize(
        "status_code,body", [(400, _CREDIT_BODY), (401, _AUTH_BODY), (529, "overloaded")]
    )
    async def test_messages_returns_503_instead_of_piping_the_error_through(
        self, db, status_code: int, body: str
    ):
        with _patch_lookup(_user("active")), _FakeAnthropic(
            _FakeStreamResponse(status_code, [], body=body.encode("utf-8"))
        ):
            response = await proxy_messages(_request(), db=db)

        # Before the fix this was a 200 text/event-stream carrying the error.
        assert response.status_code == 503
        assert json.loads(bytes(response.body)) == {"detail": _SERVICE_UNAVAILABLE}

    async def test_messages_still_streams_a_healthy_response(self, db):
        with _patch_lookup(_user("active")), _FakeAnthropic(
            _FakeStreamResponse(200, [], chunks=[b"event: message_start\n", b"data: {}\n"])
        ):
            response = await proxy_messages(_request(), db=db)
            chunks = [chunk async for chunk in response.body_iterator]

        assert response.media_type == "text/event-stream"
        assert b"".join(chunks) == b"event: message_start\ndata: {}\n"

    async def test_the_body_is_logged_even_though_it_is_not_returned(
        self, db, db_factory, caplog
    ):
        with caplog.at_level(logging.ERROR, logger="app.routes.proxy"):
            with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
                _FakeStreamResponse(400, [], body=_CREDIT_BODY.encode("utf-8"))
            ):
                response = await proxy_generate_stream(_request(), db=db)
                await _collect(response)

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "/proxy/generate-stream" in logged
        assert "400" in logged
        assert "credit balance" in logged.lower()


class TestOperatorAlert:
    """The push exists so the operator hears about an outage before a
    subscriber does, and the rate limit exists so 150 identical failures inside
    the window are one push rather than 150."""

    async def test_fires_once_for_two_failures_inside_the_window(self, db, db_factory):
        settings.ops_ntfy_url = "https://ntfy.sh/cp-ops-test"
        sent: list[str] = []

        async def _record(message: str) -> None:
            sent.append(message)

        with patch.object(ops_alert, "_post", _record):
            for _ in range(2):
                with _patch_lookup(_user("active")), _patch_sessions(
                    db_factory
                ), _FakeAnthropic(
                    _FakeStreamResponse(400, [], body=_CREDIT_BODY.encode("utf-8"))
                ):
                    response = await proxy_generate_stream(_request(), db=db)
                    await _collect(response)
            await _drain_alerts()

        assert len(sent) == 1
        assert "/proxy/generate-stream" in sent[0]
        assert "400" in sent[0]
        assert "credit balance" in sent[0].lower()

    async def test_no_alert_and_no_network_call_when_the_setting_is_empty(
        self, db, db_factory
    ):
        settings.ops_ntfy_url = ""
        sent: list[str] = []

        async def _record(message: str) -> None:
            sent.append(message)

        with patch.object(ops_alert, "_post", _record):
            with _patch_lookup(_user("active")), _patch_sessions(db_factory), _FakeAnthropic(
                _FakeStreamResponse(401, [], body=_AUTH_BODY.encode("utf-8"))
            ):
                response = await proxy_generate_stream(_request(), db=db)
                records = await _collect(response)
            await _drain_alerts()

        assert sent == []
        assert records == [{"error": _SERVICE_UNAVAILABLE}]
