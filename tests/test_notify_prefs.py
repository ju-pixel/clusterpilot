"""Cloud notification preferences gate which events the local daemon sends.

Issue #5: the dashboard's Notifications page wrote preferences nothing ever
read. The daemon now fetches them once at reconcile and consults them before
each notification. These tests pin two contracts:

  1. ``fetch_notification_preferences`` returns None on anything unexpected
     (no token, HTTP error, network failure, wrong shape), never a set of
     all-False switches, because None means "local config decides".
  2. ``PollDaemon._should_notify`` allows everything when there are no cloud
     preferences, and otherwise honours the stored boolean. An event the
     dashboard has no switch for stays allowed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.config import Config, Defaults, HostedConfig
from clusterpilot.jobs.daemon import PollDaemon
from clusterpilot.jobs.sync import (
    NotificationPreferences,
    fetch_notification_preferences,
)

_ALL_ON = {
    "notify_on_start": True,
    "notify_on_complete": True,
    "notify_on_fail": True,
    "notify_on_walltime_warn": True,
    "ntfy_topic": "https://ntfy.sh/julia-jobs",
}


def _mock_http_client(status_code: int = 200, payload: object = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "" if status_code < 400 else "boom"
    resp.json = MagicMock(return_value=payload if payload is not None else _ALL_ON)
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)
    return client


def _daemon(prefs: NotificationPreferences | None = None) -> PollDaemon:
    daemon = PollDaemon(Config(defaults=Defaults()), db_path=":memory:")
    daemon._cloud_prefs = prefs
    return daemon


class TestFetchPreferences:
    async def test_returns_none_without_token(self):
        # Self-hosted users have no cloud account to ask.
        result = await fetch_notification_preferences(HostedConfig(api_token=""))
        assert result is None

    async def test_parses_the_api_payload(self):
        payload = dict(_ALL_ON, notify_on_fail=False, notify_on_walltime_warn=False)
        client = _mock_http_client(200, payload)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            prefs = await fetch_notification_preferences(
                HostedConfig(api_token="cp-abcd1234")
            )
        assert prefs == NotificationPreferences(
            started=True, completed=True, failed=False, low_time=False
        )

    async def test_calls_the_daemon_route_with_the_bearer_token(self):
        client = _mock_http_client(200)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            await fetch_notification_preferences(
                HostedConfig(api_url="https://api.clusterpilot.sh/",
                             api_token="cp-abcd1234")
            )
        url = client.get.await_args.args[0]
        headers = client.get.await_args.kwargs["headers"]
        assert url == "https://api.clusterpilot.sh/notify/preferences/daemon"
        assert headers["Authorization"] == "Bearer cp-abcd1234"

    async def test_returns_none_on_error_status(self):
        client = _mock_http_client(401)
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            prefs = await fetch_notification_preferences(
                HostedConfig(api_token="cp-abcd1234")
            )
        assert prefs is None

    async def test_returns_none_on_network_failure(self):
        client = _mock_http_client(200)
        client.get = AsyncMock(side_effect=OSError("connection refused"))
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            prefs = await fetch_notification_preferences(
                HostedConfig(api_token="cp-abcd1234")
            )
        assert prefs is None

    async def test_returns_none_on_unexpected_shape(self):
        client = _mock_http_client(200, payload=["not", "a", "dict"])
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            prefs = await fetch_notification_preferences(
                HostedConfig(api_token="cp-abcd1234")
            )
        assert prefs is None

    async def test_missing_fields_default_to_on(self):
        client = _mock_http_client(200, payload={"ntfy_topic": None})
        with patch("clusterpilot.jobs.sync.httpx.AsyncClient", return_value=client):
            prefs = await fetch_notification_preferences(
                HostedConfig(api_token="cp-abcd1234")
            )
        assert prefs == NotificationPreferences()


class TestShouldNotify:
    def test_allows_everything_without_cloud_prefs(self):
        daemon = _daemon(None)
        for event in ("started", "completed", "failed", "low_time", "eta"):
            assert daemon._should_notify(event) is True

    def test_honours_a_switched_off_event(self):
        daemon = _daemon(NotificationPreferences(failed=False))
        assert daemon._should_notify("failed") is False
        assert daemon._should_notify("started") is True

    def test_unknown_event_stays_allowed(self):
        # The dashboard has no switch for the periodic ETA, so it is local-only.
        daemon = _daemon(NotificationPreferences(started=False))
        assert daemon._should_notify("eta") is True
