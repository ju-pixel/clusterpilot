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
        expanded = profile.expand_scratch()
        assert "$HOME" not in expanded
        assert str(Path.home()) in expanded

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
