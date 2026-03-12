"""Configuration loading and dataclasses.

Config file lives at ~/.config/clusterpilot/config.toml.
If it doesn't exist, write_default_config() creates a template.

API key precedence: config file → ANTHROPIC_API_KEY env var.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-remodule-import]

CONFIG_PATH = Path.home() / ".config" / "clusterpilot" / "config.toml"

_DEFAULT_TOML = """\
[defaults]
model = "claude-sonnet-4-6"   # or "claude-opus-4-6" for harder jobs
api_key = ""                  # leave blank to use ANTHROPIC_API_KEY env var
poll_interval = 300           # seconds between job status checks
# upload_excludes = [".git/", "__pycache__/", "*.pyc", "*.egg-info/", ".DS_Store"]
# Override to change what is excluded from all project uploads.
# Per-project exclusions go in .clusterpilot_ignore at the project root.

[[clusters]]
name = "grex"
host = "yak.hpc.umanitoba.ca"
user = ""          # your Grex username
account = ""       # your SLURM account, e.g. def-stamps
scratch = "$HOME/clusterpilot_jobs"

[notifications]
backend = "ntfy"
ntfy_topic = ""              # your ntfy.sh topic string
ntfy_server = "https://ntfy.sh"
"""


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ClusterProfile:
    name: str
    host: str
    user: str
    account: str
    scratch: str   # may contain $HOME — call expand_scratch() to resolve

    def expand_scratch(self) -> str:
        """Return scratch path suitable for use in remote commands.

        $HOME is replaced with ~ so the remote shell expands it correctly.
        Never expand $HOME using the local home directory — the local and
        remote usernames may differ.
        """
        return self.scratch.replace("$HOME", "~")

    def remote_job_dir(self, job_name: str) -> str:
        """Absolute remote path for a named job's working directory."""
        return f"{self.expand_scratch()}/{job_name}"


@dataclass
class NotificationConfig:
    backend: str = "ntfy"
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"


_DEFAULT_UPLOAD_EXCLUDES: list[str] = [
    ".git/",
    "__pycache__/",
    "*.pyc",
    "*.egg-info/",
    ".DS_Store",
    "clusterpilot_jobs/",   # staging dir created by ClusterPilot itself
]


@dataclass
class Defaults:
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    poll_interval: int = 300
    upload_excludes: list[str] = field(default_factory=lambda: list(_DEFAULT_UPLOAD_EXCLUDES))


@dataclass
class Config:
    defaults: Defaults
    clusters: list[ClusterProfile] = field(default_factory=list)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)

    def get_cluster(self, name: str) -> ClusterProfile | None:
        """Return the cluster profile with the given name, or None."""
        for c in self.clusters:
            if c.name == name:
                return c
        return None

    @property
    def api_key(self) -> str:
        """Effective API key: config value, then ANTHROPIC_API_KEY env var."""
        return self.defaults.api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def model(self) -> str:
        return self.defaults.model

    @property
    def poll_interval(self) -> int:
        return self.defaults.poll_interval


# ── Loading ───────────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when the config file cannot be parsed or is missing required fields."""


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load and parse config.toml. Raises ConfigError on missing file or bad TOML."""
    if not path.exists():
        raise ConfigError(
            f"Config not found: {path}\n"
            f"Run: clusterpilot init   (to create a starter config)"
        )
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    return _from_dict(data)


def write_default_config(path: Path = CONFIG_PATH) -> None:
    """Write a starter config.toml template. Does NOT overwrite an existing file."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_TOML)


# ── Parsing ───────────────────────────────────────────────────────────────────

def _from_dict(data: dict) -> Config:
    raw_defaults = data.get("defaults", {})
    defaults = Defaults(
        model=raw_defaults.get("model", "claude-sonnet-4-6"),
        api_key=raw_defaults.get("api_key", ""),
        poll_interval=int(raw_defaults.get("poll_interval", 300)),
        upload_excludes=raw_defaults.get("upload_excludes", list(_DEFAULT_UPLOAD_EXCLUDES)),
    )

    clusters = [
        ClusterProfile(
            name=c["name"],
            host=c["host"],
            user=c.get("user", ""),
            account=c.get("account", ""),
            scratch=c.get("scratch", "$HOME/clusterpilot_jobs"),
        )
        for c in data.get("clusters", [])
    ]

    raw_notify = data.get("notifications", {})
    notifications = NotificationConfig(
        backend=raw_notify.get("backend", "ntfy"),
        ntfy_topic=raw_notify.get("ntfy_topic", ""),
        ntfy_server=raw_notify.get("ntfy_server", "https://ntfy.sh"),
    )

    return Config(defaults=defaults, clusters=clusters, notifications=notifications)
