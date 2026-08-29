"""Profile-aware state locations and the systemd unit that follows them.

Issue #24: config, job database, probe cache and the systemd unit were all
hardcoded off ``Path.home()``, so a development install on the research
workstation shared all four, and ``daemon install`` overwrote the research
unit in place. These tests pin the override and the refusal.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from clusterpilot import paths
from clusterpilot.jobs import daemon

# ── The CLUSTERPILOT_HOME override ────────────────────────────────────────────

class TestHome:
    def test_defaults_to_the_real_home(self, monkeypatch):
        monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)
        assert paths.home() == Path.home()

    def test_override_relocates_every_state_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path))
        assert paths.home() == tmp_path
        assert paths.config_path() == tmp_path / ".config" / "clusterpilot" / "config.toml"
        assert paths.db_path() == tmp_path / ".local" / "share" / "clusterpilot" / "jobs.db"
        assert paths.cache_root() == tmp_path / ".cache" / "clusterpilot"

    def test_a_tilde_is_expanded(self, monkeypatch):
        monkeypatch.setenv(paths.HOME_ENV_VAR, "~/cp-dev")
        assert paths.home() == Path.home() / "cp-dev"

    def test_a_blank_value_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv(paths.HOME_ENV_VAR, "   ")
        assert paths.home() == Path.home()
        assert paths.profile_suffix() == ""


class TestProfileSuffix:
    def test_empty_without_an_override(self, monkeypatch):
        monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)
        assert paths.profile_suffix() == ""
        assert paths.service_name() == "clusterpilot-poll.service"

    def test_taken_from_the_basename(self, monkeypatch, tmp_path):
        target = tmp_path / "cp-dev"
        monkeypatch.setenv(paths.HOME_ENV_VAR, str(target))
        assert paths.profile_suffix() == "cp-dev"

    def test_a_trailing_slash_does_not_blank_the_name(self, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "cp-dev") + "/")
        assert paths.profile_suffix() == "cp-dev"


class TestServiceName:
    def test_the_unit_is_qualified_by_the_profile(self, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "cp-dev"))
        assert paths.service_name() == "clusterpilot-poll-cp-dev.service"
        assert paths.service_path().name == "clusterpilot-poll-cp-dev.service"
        assert paths.service_path().parent == (
            tmp_path / "cp-dev" / ".config" / "systemd" / "user"
        )


# ── write_service_file ────────────────────────────────────────────────────────

@pytest.fixture
def unit_path(tmp_path, monkeypatch):
    """Point the daemon's unit path at a temp dir for the whole test."""
    path = tmp_path / "systemd" / "user" / "clusterpilot-poll.service"
    monkeypatch.setattr(daemon, "_SERVICE_PATH", path)
    return path


class TestWriteServiceFile:
    def test_writes_the_unit_with_the_given_interpreter(self, unit_path):
        written = daemon.write_service_file("/usr/bin/python3")
        assert written == unit_path
        text = unit_path.read_text()
        assert "ExecStart=/usr/bin/python3 -m clusterpilot daemon run" in text

    def test_rewriting_the_same_unit_is_allowed(self, unit_path):
        daemon.write_service_file("/usr/bin/python3")
        daemon.write_service_file("/usr/bin/python3")
        assert "ExecStart=/usr/bin/python3" in unit_path.read_text()

    def test_refuses_to_overwrite_a_different_exec_start(self, unit_path):
        daemon.write_service_file("/usr/bin/python3")
        with pytest.raises(daemon.ServiceExistsError) as exc:
            daemon.write_service_file("/home/juliaf/repos/clusterpilot/.venv/bin/python")
        message = str(exc.value)
        assert "/usr/bin/python3" in message      # names the unit already there
        assert "--force" in message               # names the way past it
        # The research unit is untouched by the refusal.
        assert "ExecStart=/usr/bin/python3 -m clusterpilot daemon run" in unit_path.read_text()

    def test_force_replaces_the_unit_and_keeps_a_backup(self, unit_path):
        daemon.write_service_file("/usr/bin/python3")
        daemon.write_service_file("/dev/venv/bin/python", force=True)
        assert "ExecStart=/dev/venv/bin/python" in unit_path.read_text()
        backup = unit_path.with_name(unit_path.name + ".bak")
        assert backup.exists()
        assert "ExecStart=/usr/bin/python3" in backup.read_text()

    def test_the_profile_travels_into_the_unit(self, unit_path, monkeypatch, tmp_path):
        monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "cp-dev"))
        daemon.write_service_file("/usr/bin/python3")
        text = unit_path.read_text()
        assert f"Environment={paths.HOME_ENV_VAR}={tmp_path / 'cp-dev'}" in text
        # The line must come before ExecStart, or systemd would not apply it.
        assert text.index("Environment=") < text.index("ExecStart=")

    def test_no_environment_line_for_the_default_profile(self, unit_path, monkeypatch):
        monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)
        daemon.write_service_file("/usr/bin/python3")
        assert "Environment=" not in unit_path.read_text()
