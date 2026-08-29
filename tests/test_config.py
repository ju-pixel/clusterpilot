"""Tests for config.py — loading, parsing, dataclass helpers."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from clusterpilot.config import (
    ClusterProfile,
    Config,
    ConfigError,
    Defaults,
    NotificationConfig,
    _from_dict,
    load_config,
    write_default_config,
)


# ── _from_dict ────────────────────────────────────────────────────────────────

class TestFromDict:
    def test_full_config(self):
        data = {
            "defaults": {
                "model": "claude-opus-4-6",
                "api_key": "sk-test",
                "poll_interval": 120,
            },
            "clusters": [
                {
                    "name": "grex",
                    "host": "yak.hpc.umanitoba.ca",
                    "user": "juliaf",
                    "account": "def-stamps",
                    "scratch": "$HOME/clusterpilot_jobs",
                }
            ],
            "notifications": {
                "backend": "ntfy",
                "ntfy_topic": "my-topic",
                "ntfy_server": "https://ntfy.sh",
            },
        }
        cfg = _from_dict(data)
        assert cfg.defaults.model == "claude-opus-4-6"
        assert cfg.defaults.api_key == "sk-test"
        assert cfg.defaults.poll_interval == 120
        assert len(cfg.clusters) == 1
        assert cfg.clusters[0].name == "grex"
        assert cfg.notifications.ntfy_topic == "my-topic"

    def test_minimal_config_uses_defaults(self):
        cfg = _from_dict({"clusters": [{"name": "grex", "host": "grex.example.com"}]})
        assert cfg.defaults.model == "claude-sonnet-4-6"
        assert cfg.defaults.poll_interval == 300
        assert cfg.clusters[0].user == ""
        assert cfg.notifications.ntfy_server == "https://ntfy.sh"

    def test_empty_clusters_list(self):
        cfg = _from_dict({})
        assert cfg.clusters == []

    def test_multiple_clusters(self):
        data = {
            "clusters": [
                {"name": "grex", "host": "grex.example.com"},
                {"name": "cedar", "host": "cedar.computecanada.ca"},
            ]
        }
        cfg = _from_dict(data)
        assert len(cfg.clusters) == 2


# ── Config methods ────────────────────────────────────────────────────────────

class TestConfigMethods:
    @pytest.fixture
    def cfg(self):
        return Config(
            defaults=Defaults(model="claude-sonnet-4-6", api_key="", poll_interval=300),
            clusters=[
                ClusterProfile(
                    name="grex",
                    host="yak.hpc.umanitoba.ca",
                    user="juliaf",
                    account="def-stamps",
                    scratch="$HOME/clusterpilot_jobs",
                )
            ],
        )

    def test_get_cluster_found(self, cfg):
        profile = cfg.get_cluster("grex")
        assert profile is not None
        assert profile.host == "yak.hpc.umanitoba.ca"

    def test_get_cluster_not_found(self, cfg):
        assert cfg.get_cluster("cedar") is None

    def test_api_key_from_config(self, cfg):
        cfg.defaults.api_key = "sk-from-config"
        assert cfg.api_key == "sk-from-config"

    def test_api_key_from_env(self, cfg, monkeypatch):
        cfg.defaults.api_key = ""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        assert cfg.api_key == "sk-from-env"

    def test_api_key_config_takes_precedence(self, cfg, monkeypatch):
        cfg.defaults.api_key = "sk-config"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        assert cfg.api_key == "sk-config"

    def test_api_key_empty_when_neither_set(self, cfg, monkeypatch):
        cfg.defaults.api_key = ""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert cfg.api_key == ""

    def test_model_property(self, cfg):
        assert cfg.model == "claude-sonnet-4-6"

    def test_poll_interval_property(self, cfg):
        assert cfg.poll_interval == 300


# ── ClusterProfile helpers ────────────────────────────────────────────────────

class TestClusterProfile:
    @pytest.fixture
    def profile(self):
        return ClusterProfile(
            name="grex",
            host="yak.hpc.umanitoba.ca",
            user="juliaf",
            account="def-stamps",
            scratch="$HOME/clusterpilot_jobs",
        )

    def test_expand_scratch_replaces_home(self, profile):
        # $HOME becomes ~ so the REMOTE shell expands it. The local home must
        # never appear: local and cluster usernames differ (issue #17).
        expanded = profile.expand_scratch()
        assert expanded == "~/clusterpilot_jobs"
        assert "$HOME" not in expanded
        assert str(Path.home()) not in expanded

    def test_expand_scratch_no_home_variable(self):
        profile = ClusterProfile(
            name="grex", host="grex.example.com", user="u", account="", scratch="/abs/path"
        )
        assert profile.expand_scratch() == "/abs/path"

    def test_remote_job_dir(self, profile):
        job_dir = profile.remote_job_dir("my_experiment")
        assert job_dir.endswith("/my_experiment")
        assert "$HOME" not in job_dir


# ── load_config ───────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_raises_config_error_when_missing(self, tmp_path):
        with pytest.raises(ConfigError, match="Config not found"):
            load_config(tmp_path / "nonexistent.toml")

    def test_raises_config_error_on_invalid_toml(self, tmp_path):
        bad_file = tmp_path / "config.toml"
        bad_file.write_text("this is [not valid toml{{")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(bad_file)

    def test_loads_valid_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[defaults]\n"
            'model = "claude-sonnet-4-6"\n'
            'api_key = ""\n'
            "poll_interval = 300\n\n"
            "[[clusters]]\n"
            'name = "grex"\n'
            'host = "yak.hpc.umanitoba.ca"\n'
            'user = "juliaf"\n'
            'account = "def-stamps"\n'
            'scratch = "$HOME/clusterpilot_jobs"\n'
        )
        cfg = load_config(config_file)
        assert cfg.clusters[0].name == "grex"

    def test_appends_fieldnotes_section_when_missing(self, tmp_path):
        # A config written before the Fieldnotes integration gains a working,
        # disabled-by-default [fieldnotes] section on load.
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[defaults]\n"
            'model = "claude-sonnet-4-6"\n\n'
            "[hosted]\n"
            'api_token = ""\n'
        )
        cfg = load_config(config_file)
        assert "[fieldnotes]" in config_file.read_text()
        assert cfg.fieldnotes.enabled is False
        assert cfg.fieldnotes.project == ""


# ── [fieldnotes] parsing ──────────────────────────────────────────────────────

class TestFieldnotesConfig:
    def test_defaults_off(self):
        cfg = _from_dict({"clusters": []})
        assert cfg.fieldnotes.enabled is False
        assert cfg.fieldnotes.project == ""

    def test_parses_enabled_and_project(self):
        cfg = _from_dict(
            {"fieldnotes": {"enabled": True, "project": "spin-glass"}}
        )
        assert cfg.fieldnotes.enabled is True
        assert cfg.fieldnotes.project == "spin-glass"


# ── write_default_config ──────────────────────────────────────────────────────

class TestWriteDefaultConfig:
    def test_creates_file(self, tmp_path):
        path = tmp_path / "sub" / "config.toml"
        write_default_config(path)
        assert path.exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("existing content")
        write_default_config(path)
        assert path.read_text() == "existing content"


# ── cluster_type validation and inference (#21) ───────────────────────────────

class TestClusterTypeResolution:
    """Issue #21: cluster_type was unvalidated, case-sensitive and silently generic."""

    def _cluster(self, **kwargs) -> dict:
        base = {"name": "narval", "host": "narval.alliancecan.ca"}
        base.update(kwargs)
        return {"clusters": [base]}

    def test_an_explicit_value_is_kept(self):
        cfg = _from_dict(self._cluster(cluster_type="drac"))
        assert cfg.clusters[0].cluster_type == "drac"
        assert cfg.clusters[0].inferred_cluster_type is False

    def test_the_value_is_case_insensitive(self):
        cfg = _from_dict(self._cluster(cluster_type="DRAC"))
        assert cfg.clusters[0].cluster_type == "drac"

    def test_an_unknown_value_is_refused(self):
        with pytest.raises(ConfigError) as exc:
            _from_dict(self._cluster(cluster_type="cedar"))
        message = str(exc.value)
        assert "narval" in message
        for valid in ("drac", "grex", "generic"):
            assert valid in message

    def test_an_alliance_host_infers_drac(self):
        cfg = _from_dict(self._cluster())
        assert cfg.clusters[0].cluster_type == "drac"
        assert cfg.clusters[0].inferred_cluster_type is True

    def test_a_computecanada_host_infers_drac(self):
        cfg = _from_dict(self._cluster(host="cedar.computecanada.ca"))
        assert cfg.clusters[0].cluster_type == "drac"

    def test_a_umanitoba_host_infers_grex(self):
        cfg = _from_dict(self._cluster(host="yak.hpc.umanitoba.ca"))
        assert cfg.clusters[0].cluster_type == "grex"

    def test_an_unknown_host_infers_generic(self):
        cfg = _from_dict(self._cluster(host="hpc.example.org"))
        assert cfg.clusters[0].cluster_type == "generic"

    def test_inference_warns_once_naming_the_value(self, caplog):
        with caplog.at_level("WARNING", logger="clusterpilot.config"):
            _from_dict(self._cluster())
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "drac" in warnings[0].getMessage()
        assert "narval" in warnings[0].getMessage()

    def test_the_starter_template_tells_the_user_to_set_it(self):
        from clusterpilot.config import _DEFAULT_TOML
        line = [ln for ln in _DEFAULT_TOML.splitlines() if "cluster_type" in ln][0]
        assert "REQUIRED" in line


# ── ntfy_server path handling (#26) ───────────────────────────────────────────

class TestNtfyServerResolution:
    """Issue #26: a server URL ending in the topic produced .../topic/topic."""

    def _notify(self, server: str, topic: str = "my-topic") -> dict:
        return {"notifications": {"ntfy_topic": topic, "ntfy_server": server}}

    def test_a_plain_server_is_untouched(self):
        cfg = _from_dict(self._notify("https://ntfy.sh"))
        assert cfg.notifications.ntfy_server == "https://ntfy.sh"

    def test_a_repeated_topic_is_stripped(self):
        cfg = _from_dict(self._notify("https://ntfy.sh/my-topic"))
        assert cfg.notifications.ntfy_server == "https://ntfy.sh"
        assert cfg.notifications.resolved_url == "https://ntfy.sh/my-topic"

    def test_stripping_the_topic_warns(self, caplog):
        with caplog.at_level("WARNING", logger="clusterpilot.config"):
            _from_dict(self._notify("https://ntfy.sh/my-topic"))
        assert any("my-topic" in r.getMessage() for r in caplog.records)

    def test_a_self_hosted_server_keeps_its_host(self):
        cfg = _from_dict(self._notify("https://ntfy.lab.example/my-topic"))
        assert cfg.notifications.ntfy_server == "https://ntfy.lab.example"

    def test_any_other_path_is_refused(self):
        with pytest.raises(ConfigError) as exc:
            _from_dict(self._notify("https://ntfy.sh/some-other-topic"))
        assert "ntfy_topic" in str(exc.value)

    def test_a_trailing_slash_is_not_a_path(self):
        cfg = _from_dict(self._notify("https://ntfy.sh/"))
        assert cfg.notifications.ntfy_server == "https://ntfy.sh"

    def test_the_resolved_url_matches_what_ntfy_posts_to(self):
        cfg = _from_dict(self._notify("https://ntfy.sh"))
        n = cfg.notifications
        assert n.resolved_url == f"{n.ntfy_server.rstrip('/')}/{n.ntfy_topic}"

    def test_no_topic_means_no_resolved_url(self):
        cfg = _from_dict(self._notify("https://ntfy.sh", topic=""))
        assert cfg.notifications.resolved_url == ""
