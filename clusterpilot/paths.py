"""Where ClusterPilot keeps its state, and how a second profile relocates it.

Every piece of ClusterPilot state used to be hardcoded off ``Path.home()``:
the config file, the job database, the probe cache and the systemd unit. On a
machine that runs ClusterPilot twice, once for real research and once for
development, that is four collisions waiting to happen, the worst of them a
``daemon install`` that overwrites the research unit in place (issue #24).

Setting ``CLUSTERPILOT_HOME`` moves all four together:

    CLUSTERPILOT_HOME=~/cp-dev clusterpilot

The systemd unit additionally takes the profile name from the basename of the
override, so ``~/cp-dev`` installs ``clusterpilot-poll-cp-dev.service`` and can
never overwrite the research unit.

The SSH ControlPath is deliberately NOT relocated. Both profiles talk to the
same clusters with the same keys, and sharing one authenticated ControlMaster
socket is exactly what is wanted; a per-profile socket would open a second
connection for no gain. ``ssh/connection.py`` therefore keeps its own real
``~/.ssh`` path.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Environment variable that relocates every ClusterPilot state directory.
HOME_ENV_VAR = "CLUSTERPILOT_HOME"

_SERVICE_STEM = "clusterpilot-poll"


def _override() -> str:
    """The raw ``CLUSTERPILOT_HOME`` value, stripped, "" when unset or blank."""
    return os.environ.get(HOME_ENV_VAR, "").strip()


def home() -> Path:
    """Base directory for ClusterPilot state.

    ``CLUSTERPILOT_HOME`` when it is set to something non-blank, expanded so a
    value such as ``~/cp-dev`` works, otherwise the user's real home.
    """
    raw = _override()
    if raw:
        return Path(raw).expanduser()
    return Path.home()


def profile_suffix() -> str:
    """Name of the active profile, "" for the default one.

    The basename of the override, so ``~/cp-dev`` is the profile ``cp-dev``.
    """
    raw = _override()
    if not raw:
        return ""
    return Path(raw).expanduser().name


def config_path() -> Path:
    """Absolute path of config.toml for the active profile."""
    return home() / ".config" / "clusterpilot" / "config.toml"


def db_path() -> Path:
    """Absolute path of the job database for the active profile."""
    return home() / ".local" / "share" / "clusterpilot" / "jobs.db"


def cache_root() -> Path:
    """Root of the probe cache for the active profile."""
    return home() / ".cache" / "clusterpilot"


def service_name() -> str:
    """Systemd unit name, profile-qualified so two profiles cannot collide."""
    suffix = profile_suffix()
    return f"{_SERVICE_STEM}-{suffix}.service" if suffix else f"{_SERVICE_STEM}.service"


def service_path() -> Path:
    """Absolute path of the systemd user unit for the active profile."""
    return home() / ".config" / "systemd" / "user" / service_name()
