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
  3. Issue #43: the topic typed on the same page is read too. When set, the
     daemon posts there instead of to the topic in config.toml; a URL also
     picks the server, a bare topic keeps the local one.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from clusterpilot.config import Config, Defaults, HostedConfig, NotificationConfig
from clusterpilot.db import JobRecord
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
            started=True, completed=True, failed=False, low_time=False,
            ntfy_topic="https://ntfy.sh/julia-jobs",
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


_LOCAL = NotificationConfig(ntfy_topic="local-topic", ntfy_server="https://ntfy.example.org")


class TestWithTopic:
    def test_url_sets_server_and_topic(self):
        cfg = _LOCAL.with_topic("https://ntfy.sh/julia-jobs")
        assert (cfg.ntfy_server, cfg.ntfy_topic) == ("https://ntfy.sh", "julia-jobs")
        assert cfg.resolved_url == "https://ntfy.sh/julia-jobs"

    def test_bare_topic_keeps_the_local_server(self):
        cfg = _LOCAL.with_topic("julia-jobs")
        assert (cfg.ntfy_server, cfg.ntfy_topic) == ("https://ntfy.example.org", "julia-jobs")

    def test_self_hosted_url_under_a_path_prefix(self):
        cfg = _LOCAL.with_topic("https://lab.example.org/ntfy/jobs/")
        assert (cfg.ntfy_server, cfg.ntfy_topic) == ("https://lab.example.org/ntfy", "jobs")

    def test_empty_and_server_only_change_nothing(self):
        assert _LOCAL.with_topic("") == _LOCAL
        assert _LOCAL.with_topic("   ") == _LOCAL
        assert _LOCAL.with_topic("https://ntfy.sh") == _LOCAL
        assert _LOCAL.with_topic("https://ntfy.sh/") == _LOCAL

    def test_does_not_mutate_the_original(self):
        _LOCAL.with_topic("https://ntfy.sh/other")
        assert _LOCAL.ntfy_topic == "local-topic"


def _job() -> JobRecord:
    return JobRecord(
        job_id="123", job_name="spin", cluster_name="grex", host="h", user="u",
        account="", partition="p", script_path="", working_dir="", local_dir="",
        walltime="01:00:00", status="FAILED",
    )


class TestCloudTopic:
    def _daemon_with(self, prefs: NotificationPreferences | None) -> PollDaemon:
        daemon = _daemon(prefs)
        daemon.config.notifications = _LOCAL
        return daemon

    def test_local_config_without_cloud_prefs(self):
        assert self._daemon_with(None)._notifications() == _LOCAL

    def test_local_config_when_the_dashboard_topic_is_empty(self):
        daemon = self._daemon_with(NotificationPreferences(ntfy_topic=""))
        assert daemon._notifications() == _LOCAL

    def test_dashboard_topic_wins_when_set(self):
        daemon = self._daemon_with(
            NotificationPreferences(ntfy_topic="https://ntfy.sh/julia-jobs")
        )
        assert daemon._notifications().resolved_url == "https://ntfy.sh/julia-jobs"

    def test_dashboard_topic_fills_an_empty_local_topic(self):
        # Hosted user who never set [notifications] locally still gets pushes.
        daemon = self._daemon_with(NotificationPreferences(ntfy_topic="https://ntfy.sh/jobs"))
        daemon.config.notifications = NotificationConfig()
        assert daemon._notifications().resolved_url == "https://ntfy.sh/jobs"

    async def test_failure_notification_is_posted_to_the_dashboard_topic(self):
        daemon = self._daemon_with(
            NotificationPreferences(ntfy_topic="https://ntfy.sh/julia-jobs")
        )
        sent = AsyncMock()
        with patch("clusterpilot.jobs.daemon.notify_failed", sent), \
             patch.object(daemon, "_failure_excerpt", AsyncMock(return_value="")), \
             patch.object(daemon, "_sync", AsyncMock()):
            await daemon._notify_failed(MagicMock(), _job(), "FAILED")
        cfg = sent.await_args.args[0]
        assert cfg.resolved_url == "https://ntfy.sh/julia-jobs"
