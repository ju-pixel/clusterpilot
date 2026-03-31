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
provider = "anthropic"        # "anthropic", "openai", or "ollama"
model = "claude-sonnet-4-6"   # model name for the chosen provider
api_key = ""                  # API key (not required for ollama)
                              #   anthropic: set here or export ANTHROPIC_API_KEY
                              #   openai:    set here or export OPENAI_API_KEY
api_base_url = ""             # leave blank for defaults; for ollama set to http://localhost:11434/v1
poll_interval = 300           # seconds between job status checks
# upload_excludes = [".git/", "__pycache__/", "*.pyc", "*.egg-info/", ".DS_Store"]
# Override to change what is excluded from all project uploads.
# Per-project exclusions go in .clusterpilot_ignore at the project root.

[[clusters]]
name = "grex"
host = "yak.hpc.umanitoba.ca"
user = ""          # your Grex username
account = ""       # your SLURM account, e.g. def-stamps (leave blank if not required)
scratch = "$HOME/clusterpilot_jobs"
cluster_type = "grex"   # "drac", "grex", or "generic" (any other SLURM cluster)

[notifications]
backend = "ntfy"
ntfy_topic = ""              # your ntfy.sh topic string
ntfy_server = "https://ntfy.sh"

[hosted]
api_url = "https://api.clusterpilot.sh"
api_token = ""               # cp-<token> from the dashboard (leave blank for self-hosted)
"""


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ClusterProfile:
    name: str
    host: str
    user: str
    account: str
    scratch: str        # may contain $HOME — call expand_scratch() to resolve
    cluster_type: str = "generic"   # "drac", "grex", or "generic"

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


@dataclass
class HostedConfig:
    api_url: str = "https://api.clusterpilot.sh"
    api_token: str = ""  # cp-<token>; empty means hosted sync is disabled


_DEFAULT_UPLOAD_EXCLUDES: list[str] = [
    ".git/",
    "__pycache__/",
    "*.pyc",
    "*.egg-info/",
    ".DS_Store",
    "CLAUDE.md",
    "clusterpilot_jobs/",   # staging dir created by ClusterPilot itself
]

# When downloading results, skip files that were part of the uploaded project.
# Only new files (SLURM logs, data output, etc.) are pulled back.
_DEFAULT_DOWNLOAD_EXCLUDES: list[str] = [
    "src/",
    "docs/",
    "examples/",
    "scripts/",
    "*.toml",
    "*.md",
    "*.sh",
    ".git/",
    "__pycache__/",
    ".DS_Store",
]


@dataclass
class Defaults:
    provider: str = "anthropic"   # "anthropic", "openai", or "ollama"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    api_base_url: str = ""
    poll_interval: int = 300
    upload_excludes: list[str] = field(default_factory=lambda: list(_DEFAULT_UPLOAD_EXCLUDES))
    download_excludes: list[str] = field(default_factory=lambda: list(_DEFAULT_DOWNLOAD_EXCLUDES))


@dataclass
class Config:
    defaults: Defaults
    clusters: list[ClusterProfile] = field(default_factory=list)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    hosted: HostedConfig = field(default_factory=HostedConfig)

    def get_cluster(self, name: str) -> ClusterProfile | None:
        """Return the cluster profile with the given name, or None."""
        for c in self.clusters:
            if c.name == name:
                return c
        return None

    @property
    def provider(self) -> str:
        return self.defaults.provider

    @property
    def api_key(self) -> str:
        """Effective API key: config value, then provider-specific env var."""
        if self.defaults.api_key:
            return self.defaults.api_key
        if self.defaults.provider == "openai":
            return os.environ.get("OPENAI_API_KEY", "")
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def api_base_url(self) -> str:
        """Proxy base URL, or empty string to use Anthropic directly."""
        return self.defaults.api_base_url

    @property
    def model(self) -> str:
        return self.defaults.model

    @property
    def poll_interval(self) -> int:
        return self.defaults.poll_interval


# ── Loading ───────────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when the config file cannot be parsed or is missing required fields."""


_HOSTED_SECTION = """\

[hosted]
api_url = "https://api.clusterpilot.sh"
api_token = ""               # cp-<token> from the dashboard (leave blank for self-hosted)
"""


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

    # Migration: append [hosted] section if missing (configs created before hosted tier).
    if "hosted" not in data:
        with open(path, "a") as f:
            f.write(_HOSTED_SECTION)

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
        provider=raw_defaults.get("provider", "anthropic"),
        model=raw_defaults.get("model", "claude-sonnet-4-6"),
        api_key=raw_defaults.get("api_key", ""),
        api_base_url=raw_defaults.get("api_base_url", ""),
        poll_interval=int(raw_defaults.get("poll_interval", 300)),
        upload_excludes=raw_defaults.get("upload_excludes", list(_DEFAULT_UPLOAD_EXCLUDES)),
        download_excludes=raw_defaults.get("download_excludes", list(_DEFAULT_DOWNLOAD_EXCLUDES)),
    )

    clusters = [
        ClusterProfile(
            name=c["name"],
            host=c["host"],
            user=c.get("user", ""),
            account=c.get("account", ""),
            scratch=c.get("scratch", "$HOME/clusterpilot_jobs"),
            cluster_type=c.get("cluster_type", "generic"),
        )
        for c in data.get("clusters", [])
    ]

    raw_notify = data.get("notifications", {})
    notifications = NotificationConfig(
        backend=raw_notify.get("backend", "ntfy"),
        ntfy_topic=raw_notify.get("ntfy_topic", ""),
        ntfy_server=raw_notify.get("ntfy_server", "https://ntfy.sh"),
    )

    raw_hosted = data.get("hosted", {})
    hosted = HostedConfig(
        api_url=raw_hosted.get("api_url", "https://api.clusterpilot.sh"),
        api_token=raw_hosted.get("api_token", ""),
    )

    return Config(defaults=defaults, clusters=clusters, notifications=notifications, hosted=hosted)
