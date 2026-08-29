"""This month's generation allowance: the fetch, and the F9 row it fills.

Hosted users draw Opus generations from a monthly allowance. Two contracts are
pinned here:

  1. ``fetch_allowance`` returns None on anything unexpected (no token, HTTP
     error, network failure, wrong shape), never a zeroed Allowance, because a
     zero would read as an allowance already spent.
  2. F9 shows the row only for a hosted user, never blocks its own render on
     the request, and says "unknown" rather than a made-up figure when the
     request fails.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.config import ClusterProfile, Config, Defaults, HostedConfig
from clusterpilot.jobs.sync import Allowance, fetch_allowance
from clusterpilot.tui.app import ClusterPilotApp

TERMINAL_SIZE = (100, 30)

_PAYLOAD = {
    "month": "2026-08",
    "opus_used": 3,
    "opus_limit": 15,
    "total_used": 41,
    "total_limit": 150,
    "fallback_model": "claude-sonnet-5",
    "resets_on": "2026-09-01",
}


def _mock_http_client(status_code: int = 200, payload: object = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "" if status_code < 400 else "boom"
    resp.json = MagicMock(return_value=payload if payload is not None else _PAYLOAD)
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)
    return client


class TestFetchAllowance:
    async def test_returns_none_without_token(self):
        assert await fetch_allowance(HostedConfig(api_token="")) is None

    async def test_parses_the_api_payload(self):
        client = _mock_http_client()
        with patch("httpx.AsyncClient", return_value=client):
            allowance = await fetch_allowance(HostedConfig(api_token="cp-abc"))
        assert allowance == Allowance(
            month="2026-08",
            opus_used=3,
            opus_limit=15,
            total_used=41,
            total_limit=150,
            fallback_model="claude-sonnet-5",
            resets_on="2026-09-01",
        )

    async def test_calls_the_allowance_route_with_a_bearer_token(self):
        client = _mock_http_client()
        with patch("httpx.AsyncClient", return_value=client):
            await fetch_allowance(
                HostedConfig(api_url="https://api.clusterpilot.sh/", api_token="cp-abc")
            )
        url = client.get.await_args.args[0]
        headers = client.get.await_args.kwargs["headers"]
        assert url == "https://api.clusterpilot.sh/proxy/allowance"
        assert headers == {"Authorization": "Bearer cp-abc"}

    async def test_returns_none_on_an_http_error(self):
        client = _mock_http_client(403)
        with patch("httpx.AsyncClient", return_value=client):
            assert await fetch_allowance(HostedConfig(api_token="cp-abc")) is None

    async def test_returns_none_on_a_network_failure(self):
        client = _mock_http_client()
        client.get = AsyncMock(side_effect=OSError("no route to host"))
        with patch("httpx.AsyncClient", return_value=client):
            assert await fetch_allowance(HostedConfig(api_token="cp-abc")) is None

    async def test_returns_none_on_an_unexpected_shape(self):
        client = _mock_http_client(200, ["not", "a", "dict"])
        with patch("httpx.AsyncClient", return_value=client):
            assert await fetch_allowance(HostedConfig(api_token="cp-abc")) is None

    async def test_returns_none_on_non_numeric_counts(self):
        client = _mock_http_client(200, dict(_PAYLOAD, opus_used="lots"))
        with patch("httpx.AsyncClient", return_value=client):
            assert await fetch_allowance(HostedConfig(api_token="cp-abc")) is None


# ── F9 ────────────────────────────────────────────────────────────────────────

def _config(token: str) -> Config:
    return Config(
        defaults=Defaults(api_key="test-key"),
        clusters=[
            ClusterProfile(
                name="testcluster",
                host="test.example.org",
                user="tester",
                account="def-test",
                scratch="$HOME/scratch",
                cluster_type="generic",
            )
        ],
        hosted=HostedConfig(api_token=token),
    )


@contextlib.contextmanager
def _offline(allowance: Allowance | None) -> Iterator[AsyncMock]:
    """Stub the network, including the allowance fetch F9 makes on mount."""
    daemon = MagicMock()
    daemon.run_forever = AsyncMock()
    fetch = AsyncMock(return_value=allowance)
    with patch("clusterpilot.tui.app.PollDaemon", return_value=daemon), \
            patch("clusterpilot.tui.app.is_connected", return_value=False), \
            patch("clusterpilot.update.check_for_update", new=AsyncMock(return_value=None)), \
            patch("clusterpilot.tui.submit.probe_cluster",
                  new=AsyncMock(side_effect=RuntimeError("offline"))), \
            patch("clusterpilot.tui.submit.fetch_availability", new=AsyncMock(return_value={})), \
            patch("clusterpilot.tui.config_view.fetch_allowance", new=fetch):
        yield fetch


async def _config_text(
    tmp_path: Path, token: str, allowance: Allowance | None,
) -> tuple[str, AsyncMock]:
    """Open F9, let the background fetch settle, and return the rendered text."""
    from textual.widgets import Static

    app = ClusterPilotApp(_config(token), db_path=tmp_path / "jobs.db")
    with _offline(allowance) as fetch:
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await pilot.press("f9")
            # The fetch is a worker, so the row is filled a tick after the
            # first render. Pausing repeatedly is what proves it never blocked.
            for _ in range(5):
                await pilot.pause()
            text = str(app.query_one("#config-content", Static).content)
    return text, fetch


class TestConfigViewAllowanceRow:
    async def test_a_hosted_user_sees_the_allowance(self, tmp_path: Path):
        allowance = Allowance(
            month="2026-08", opus_used=3, opus_limit=15,
            total_used=41, total_limit=150,
            fallback_model="claude-sonnet-5", resets_on="2026-09-01",
        )
        text, fetch = await _config_text(tmp_path, "cp-abc", allowance)
        assert "Allowance" in text
        assert "Opus 3/15, total 41/150, resets 2026-09-01" in text
        fetch.assert_awaited()

    async def test_a_self_hosted_user_sees_no_row(self, tmp_path: Path):
        text, fetch = await _config_text(tmp_path, "", None)
        assert "Allowance" not in text
        fetch.assert_not_awaited()

    async def test_a_failed_fetch_reads_unknown(self, tmp_path: Path):
        text, _ = await _config_text(tmp_path, "cp-abc", None)
        assert "Allowance" in text
        assert "unknown" in text
