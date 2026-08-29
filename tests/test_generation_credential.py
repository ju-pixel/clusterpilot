"""Which credential pays for a generation, and where F9 says so.

Issue #25: ``Config.api_key`` fell back to the provider's environment
variable, and the hosted branch only ran when that came back empty, so an
exported ANTHROPIC_API_KEY silently took generation off the paid proxy. The
dashboard kept filling up from the separate sync path and F9 kept showing the
hosted token as active, so nothing anywhere disagreed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clusterpilot.config import Config, Defaults, HostedConfig
from clusterpilot.tui.config_view import _render
from clusterpilot.tui.submit import _generation_credential


def _config(*, api_key: str = "", token: str = "", provider: str = "anthropic",
            api_base_url: str = "") -> Config:
    return Config(
        defaults=Defaults(provider=provider, api_key=api_key, api_base_url=api_base_url),
        hosted=HostedConfig(api_url="https://api.clusterpilot.sh", api_token=token),
    )


@pytest.fixture
def no_env_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


class TestGenerationCredential:
    def test_a_config_key_is_used_directly(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
        credential = _generation_credential(_config(api_key="sk-cfg", token="cp-token"))
        assert credential.api_key == "sk-cfg"
        assert credential.hosted is False
        assert credential.api_base_url == ""
        assert credential.ignored_env_var == ""

    def test_the_hosted_proxy_is_used_when_no_config_key_is_set(self, no_env_keys):
        credential = _generation_credential(_config(token="cp-token"))
        assert credential.api_key == "cp-token"
        assert credential.hosted is True
        assert credential.api_base_url == "https://api.clusterpilot.sh/proxy"
        assert credential.ignored_env_var == ""

    def test_an_exported_key_no_longer_bypasses_the_proxy(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
        credential = _generation_credential(_config(token="cp-token"))
        assert credential.hosted is True
        assert credential.api_key == "cp-token"
        # and the user is told the exported key is being ignored.
        assert credential.ignored_env_var == "ANTHROPIC_API_KEY"

    def test_the_env_key_is_used_when_there_is_no_token(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
        credential = _generation_credential(_config())
        assert credential.api_key == "sk-ant-env"
        assert credential.hosted is False

    def test_a_hosted_token_does_not_cover_a_non_anthropic_provider(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        credential = _generation_credential(_config(token="cp-token", provider="openai"))
        assert credential.api_key == "sk-openai"
        assert credential.hosted is False

    def test_nothing_configured_yields_no_key(self, no_env_keys):
        credential = _generation_credential(_config())
        assert credential.api_key == ""
        assert credential.hosted is False

    def test_a_configured_base_url_is_kept_for_a_own_key(self, no_env_keys):
        credential = _generation_credential(
            _config(api_key="sk-cfg", api_base_url="http://localhost:11434/v1")
        )
        assert credential.api_base_url == "http://localhost:11434/v1"


class TestConfigViewGenerationRow:
    def _render_for(self, config: Config) -> str:
        app = MagicMock()
        app._config = config
        return _render(app)

    def test_names_the_hosted_proxy(self, no_env_keys):
        text = self._render_for(_config(token="cp-token"))
        assert "Generation" in text
        assert "hosted proxy" in text

    def test_names_an_exported_key_that_would_otherwise_be_invisible(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        text = self._render_for(_config())
        assert "own key (ANTHROPIC_API_KEY)" in text

    def test_a_config_key_outranks_the_hosted_token_in_the_display(self, no_env_keys):
        text = self._render_for(_config(api_key="sk-config-key", token="cp-token"))
        assert "own key (config)" in text
        assert "using managed key" not in text

    def test_says_none_when_nothing_is_configured(self, no_env_keys):
        assert "none" in self._render_for(_config())
