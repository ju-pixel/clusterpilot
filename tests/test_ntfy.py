"""Tests for notify/ntfy.py — push notification helpers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from clusterpilot.config import NotificationConfig
from clusterpilot.db import JobRecord
from clusterpilot.notify.ntfy import (
    NtfyError,
    notify_completed,
    notify_eta,
    notify_failed,
    notify_low_time,
    notify_started,
    send,
)


def _make_job(**kwargs) -> JobRecord:
    defaults = dict(
        job_id="99",
        job_name="bench_run",
        cluster_name="grex",
        host="yak.hpc.umanitoba.ca",
        user="juliaf",
        account="def-stamps",
        partition="stamps",
        script_path="/home/juliaf/jobs/bench_run/job.sh",
        working_dir="/home/juliaf/jobs/bench_run",
        local_dir="/Users/juliaf/bench",
        walltime="08:00:00",
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


def _make_notify_cfg(topic: str = "my-topic") -> NotificationConfig:
    return NotificationConfig(
        backend="ntfy", ntfy_topic=topic, ntfy_server="https://ntfy.sh"
    )


def _mock_http_client(status_code: int = 200):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=MagicMock()
        )
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


# ── send ──────────────────────────────────────────────────────────────────────

class TestSend:
    async def test_posts_to_correct_url(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("my-topic", "hello", server="https://ntfy.sh")

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://ntfy.sh/my-topic"

    async def test_includes_title_header(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("topic", "body", title="My Title", server="https://ntfy.sh")

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Title"] == "My Title"

    async def test_includes_tags_header_when_given(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("topic", "body", tags=["rocket", "tada"], server="https://ntfy.sh")

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Tags"] == "rocket,tada"

    async def test_no_tags_header_when_tags_none(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("topic", "body", server="https://ntfy.sh")

        headers = mock_client.post.call_args[1]["headers"]
        assert "Tags" not in headers

    async def test_skips_silently_when_topic_empty(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("", "hello")   # should not POST

        mock_client.post.assert_not_called()

    async def test_raises_ntfy_error_on_http_failure(self):
        mock_client = _mock_http_client(status_code=500)
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(NtfyError, match="ntfy POST failed"):
                await send("topic", "hello", server="https://ntfy.sh")

    async def test_trailing_slash_stripped_from_server(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("topic", "body", server="https://ntfy.sh/")

        url = mock_client.post.call_args[0][0]
        assert url == "https://ntfy.sh/topic"

    async def test_encodes_message_as_bytes(self):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await send("topic", "hello", server="https://ntfy.sh")

        content = mock_client.post.call_args[1]["content"]
        assert content == b"hello"


# ── job event helpers ─────────────────────────────────────────────────────────

class TestJobEventHelpers:
    @pytest.fixture
    def cfg(self):
        return _make_notify_cfg()

    @pytest.fixture
    def job(self):
        return _make_job()

    async def test_notify_started_sends_rocket_tag(self, cfg, job):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_started(cfg, job)

        headers = mock_client.post.call_args[1]["headers"]
        assert "rocket" in headers.get("Tags", "")

    async def test_notify_completed_uses_high_priority(self, cfg, job):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_completed(cfg, job)

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Priority"] == "high"

    async def test_notify_failed_includes_log_excerpt(self, cfg, job):
        # 20 lines: "line 0" … "line 19". Last 6 = lines 14–19.
        long_log = "\n".join(f"line {i}" for i in range(20))
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_failed(cfg, job, log_tail=long_log)

        body = mock_client.post.call_args[1]["content"].decode()
        assert "line 19" in body
        assert "line 14" in body
        assert "line 13" not in body  # 7th from end, outside the 6-line window

    async def test_notify_failed_without_log(self, cfg, job):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_failed(cfg, job)  # no log_tail

        mock_client.post.assert_called_once()

    async def test_notify_eta_formats_hours_and_minutes(self, cfg, job):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_eta(cfg, job, eta_minutes=90)

        body = mock_client.post.call_args[1]["content"].decode()
        assert "1h 30m" in body

    async def test_notify_eta_minutes_only(self, cfg, job):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_eta(cfg, job, eta_minutes=45)

        body = mock_client.post.call_args[1]["content"].decode()
        assert "45m" in body
        assert "0h" not in body

    async def test_notify_low_time_uses_high_priority(self, cfg, job):
        mock_client = _mock_http_client()
        with patch("clusterpilot.notify.ntfy.httpx.AsyncClient", return_value=mock_client):
            await notify_low_time(cfg, job, minutes_left=10)

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Priority"] == "high"
