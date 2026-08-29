"""Configuration loading and dataclasses.

Config file lives at ~/.config/clusterpilot/config.toml, or under
$CLUSTERPILOT_HOME when that is set (see paths.py).
If it doesn't exist, write_default_config() creates a template.

Credential precedence for AI script generation: [defaults] api_key in the
config file, then [hosted] api_token through the managed proxy, then the
provider's environment variable. See Config.generation_source.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from clusterpilot import paths

log = logging.getLogger(__name__)

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-remodule-import]

# Resolved once at import. Set CLUSTERPILOT_HOME to relocate this, the job
# database, the probe cache and the systemd unit together (see paths.py).
CONFIG_PATH = paths.config_path()

_DEFAULT_TOML = """\
[defaults]
provider = "anthropic"        # "anthropic", "openai", or "ollama"
model = "claude-sonnet-4-6"   # model name for the chosen provider
api_key = ""                  # API key (not required for ollama)
                              #   anthropic: set here or export ANTHROPIC_API_KEY
                              #   openai:    set here or export OPENAI_API_KEY
api_base_url = ""             # leave blank for defaults; for ollama set to http://localhost:11434/v1
poll_interval = 300           # seconds between job status checks
# upload_excludes = [".git/", ".julia/", "__pycache__/", "node_modules/", "*.png", "*.h5", ...]
# Override to change what is excluded from all project uploads (rsync glob syntax).
# Defaults already cover VCS/caches/build artefacts and large media globs.
# Per-project exclusions go in .clusterpilotignore at the project root.

[[clusters]]
name = "grex"
host = "yak.hpc.umanitoba.ca"
user = ""          # your Grex username
account = ""       # your SLURM account, e.g. def-stamps (leave blank if not required)
scratch = "$HOME/clusterpilot_jobs"
cluster_type = "grex"   # REQUIRED, set it per cluster: "drac" (Alliance/DRAC),
                        # "trillium" (Alliance Trillium at SciNet: whole-node
                        # scheduling, 24 h cap, read-only $HOME on compute
                        # nodes), "grex" (UofM Grex), or "generic" (any other
                        # SLURM cluster). Copying this stanza for a different
                        # cluster means changing this line too: the wrong value
                        # silently generates scripts the scheduler rejects.

[notifications]
backend = "ntfy"
ntfy_topic = ""              # your ntfy.sh topic string
ntfy_server = "https://ntfy.sh"

[hosted]
api_url = "https://api.clusterpilot.sh"
api_token = ""               # cp-<token> from the dashboard (leave blank for self-hosted)

[fieldnotes]
enabled = false              # log completed runs into local Fieldnotes (needs the fieldnotes CLI)
# project = "my-project"     # optional: file all runs under this named Fieldnotes project
"""


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ClusterProfile:
    name: str
    host: str
    user: str
    account: str
    scratch: str        # may contain $HOME — call expand_scratch() to resolve
    cluster_type: str = "generic"   # "drac", "trillium", "grex", or "generic"
    inferred_cluster_type: bool = False   # True when cluster_type was guessed
                                          # from the host, not read from config

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

    @property
    def resolved_url(self) -> str:
        """The URL a notification is actually POSTed to.

        Mirrors what ``notify.ntfy.send`` builds, so the F9 view and the
        transport can never disagree about where a notification goes.
        """
        if not self.ntfy_topic:
            return ""
        return f"{self.ntfy_server.rstrip('/')}/{self.ntfy_topic}"


@dataclass
class HostedConfig:
    api_url: str = "https://api.clusterpilot.sh"
    api_token: str = ""  # cp-<token>; empty means hosted sync is disabled


@dataclass
class FieldnotesConfig:
    """Opt-in local logging of completed runs into the Fieldnotes CLI.

    Off by default so ClusterPilot never touches Fieldnotes unless the user
    asks. When enabled, requires the `fieldnotes` binary on PATH; if it is
    absent the integration silently no-ops.
    """
    enabled: bool = False   # opt-in; requires the fieldnotes CLI on PATH
    project: str = ""       # optional Fieldnotes project name; "" lets
                            # Fieldnotes attribute runs by directory


_DEFAULT_UPLOAD_EXCLUDES: list[str] = [
    # Version control, caches, build artefacts — never needed on the cluster.
    ".git/",
    ".julia/",
    "__pycache__/",
    "*.pyc",
    ".ipynb_checkpoints/",
    "node_modules/",
    "*.egg-info/",
    ".DS_Store",
    "CLAUDE.md",
    "clusterpilot_jobs/",   # staging dir created by ClusterPilot itself
    # Large / media artefacts. A job rarely needs these as inputs; when it does,
    # add the specific file via EXTRA FILES (which bypasses these excludes).
    "*.jld2",
    "*.h5",
    "*.hdf5",
    "*.png",
    "*.pdf",
    "*.svg",
    "*.gif",
    "*.mp4",
    "*.zip",
    "*.tar*",
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
    fieldnotes: FieldnotesConfig = field(default_factory=FieldnotesConfig)

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
    def env_var_name(self) -> str:
        """The environment variable this provider reads its key from."""
        return "OPENAI_API_KEY" if self.defaults.provider == "openai" else "ANTHROPIC_API_KEY"

    @property
    def env_api_key(self) -> str:
        """The provider's key as taken from the environment, "" when unset."""
        return os.environ.get(self.env_var_name, "")

    @property
    def api_key(self) -> str:
        """Effective own key: config value, then provider-specific env var.

        This is the user's OWN credential only. The hosted proxy token is a
        separate credential on a separate base URL, so it deliberately does not
        appear here; ``generation_source`` is what says which of the two pays
        for a generation.
        """
        if self.defaults.api_key:
            return self.defaults.api_key
        return self.env_api_key

    @property
    def generation_source(self) -> str:
        """Which credential AI script generation will actually use.

        Precedence: ``[defaults] api_key`` in config, then ``[hosted]
        api_token`` through the managed proxy, then the provider's environment
        variable. An exported key used to win over a paid subscription without
        a word anywhere in the interface (issue #25), so this string is shown
        on F9 rather than left to be inferred from three separate rows.
        """
        if self.defaults.api_key:
            return "own key (config)"
        if self.hosted.api_token and self.defaults.provider == "anthropic":
            return "hosted proxy"
        if self.env_api_key:
            return f"own key ({self.env_var_name})"
        return "none"

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

_FIELDNOTES_SECTION = """\

[fieldnotes]
enabled = false              # log completed runs into local Fieldnotes (needs the fieldnotes CLI)
# project = "my-project"     # optional: file all runs under this named Fieldnotes project
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

    # Migration: append [fieldnotes] section if missing (configs created before
    # the Fieldnotes integration). Off by default, so existing behaviour is kept.
    if "fieldnotes" not in data:
        with open(path, "a") as f:
            f.write(_FIELDNOTES_SECTION)

    return _from_dict(data)


def write_default_config(path: Path = CONFIG_PATH) -> None:
    """Write a starter config.toml template. Does NOT overwrite an existing file."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_TOML)


# ── Parsing ───────────────────────────────────────────────────────────────────

VALID_CLUSTER_TYPES: frozenset[str] = frozenset(
    {"drac", "trillium", "grex", "generic"}
)

# Host fragments that identify a cluster type when cluster_type is absent, each
# tested as a substring of the hostname. Order matters and the first match wins:
# Trillium is reached at trillium.alliancecan.ca and trillium-gpu.alliancecan.ca,
# both of which also end in .alliancecan.ca, and its quirks are not DRAC's
# (issue #29), so it has to be matched first.
_HOST_SUBSTRING_TYPES: tuple[tuple[str, str], ...] = (
    ("trillium", "trillium"),
)

# Host suffixes that identify a cluster type when cluster_type is absent.
_HOST_SUFFIX_TYPES: tuple[tuple[str, str], ...] = (
    (".alliancecan.ca", "drac"),
    (".computecanada.ca", "drac"),
    (".umanitoba.ca", "grex"),
)


def infer_cluster_type(host: str) -> str:
    """Guess a cluster type from its hostname, defaulting to "generic"."""
    hostname = host.strip().lower().rstrip(".")
    for fragment, cluster_type in _HOST_SUBSTRING_TYPES:
        if fragment in hostname:
            return cluster_type
    for suffix, cluster_type in _HOST_SUFFIX_TYPES:
        if hostname.endswith(suffix):
            return cluster_type
    return "generic"


def _resolve_cluster_type(raw: dict) -> tuple[str, bool]:
    """Return (cluster_type, inferred) for one ``[[clusters]]`` stanza.

    An explicit value is lower-cased and validated; an unknown one is a
    ConfigError rather than a silent fall back to "generic", because the wrong
    quirk set produces a script sbatch rejects or, worse, one that runs on the
    wrong hardware. An absent key is inferred from the host and warned about.
    """
    name = str(raw.get("name", "<unnamed>"))
    if "cluster_type" in raw:
        value = str(raw["cluster_type"]).strip().lower()
        if value not in VALID_CLUSTER_TYPES:
            valid = ", ".join(sorted(VALID_CLUSTER_TYPES))
            raise ConfigError(
                f"Cluster '{name}': unknown cluster_type "
                f"'{raw['cluster_type']}'. Valid values are: {valid}."
            )
        return value, False

    inferred = infer_cluster_type(str(raw.get("host", "")))
    log.warning(
        "Cluster '%s' has no cluster_type; inferred '%s' from the host. "
        "Set cluster_type explicitly in config.toml (one of: %s).",
        name, inferred, ", ".join(sorted(VALID_CLUSTER_TYPES)),
    )
    return inferred, True


def _resolve_ntfy_server(server: str, topic: str) -> tuple[str, str]:
    """Return (server, warning) for an ntfy server URL.

    ``notify.ntfy.send`` appends the topic to the server, so a server URL that
    already carries the topic would POST to ``.../topic/topic``. A path equal to
    the topic is stripped with a warning; any other path is a ConfigError,
    because there is no way to tell a mistyped topic from a URL prefix ntfy
    itself would reject.
    """
    raw = server.strip().rstrip("/")
    if not raw:
        return "https://ntfy.sh", ""

    scheme, separator, rest = raw.partition("://")
    if not separator:
        scheme, rest = "", raw
    host, _, path = rest.partition("/")
    path = path.strip("/")
    if not path:
        return raw, ""

    base = f"{scheme}://{host}" if scheme else host
    if topic and path == topic:
        return base, (
            f"ntfy_server '{raw}' already ends in the topic '{topic}'; "
            f"using '{base}' so the topic is not repeated in the URL."
        )
    raise ConfigError(
        f"ntfy_server '{raw}' must be a server URL with no path, e.g. "
        f"'https://ntfy.sh'. The topic belongs in ntfy_topic."
    )


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

    clusters: list[ClusterProfile] = []
    for c in data.get("clusters", []):
        cluster_type, inferred = _resolve_cluster_type(c)
        clusters.append(
            ClusterProfile(
                name=c["name"],
                host=c["host"],
                user=c.get("user", ""),
                account=c.get("account", ""),
                scratch=c.get("scratch", "$HOME/clusterpilot_jobs"),
                cluster_type=cluster_type,
                inferred_cluster_type=inferred,
            )
        )

    raw_notify = data.get("notifications", {})
    ntfy_topic = raw_notify.get("ntfy_topic", "")
    ntfy_server, server_warning = _resolve_ntfy_server(
        raw_notify.get("ntfy_server", "https://ntfy.sh"), ntfy_topic,
    )
    if server_warning:
        log.warning("%s", server_warning)
    notifications = NotificationConfig(
        backend=raw_notify.get("backend", "ntfy"),
        ntfy_topic=ntfy_topic,
        ntfy_server=ntfy_server,
    )

    raw_hosted = data.get("hosted", {})
    hosted = HostedConfig(
        api_url=raw_hosted.get("api_url", "https://api.clusterpilot.sh"),
        api_token=raw_hosted.get("api_token", ""),
    )

    raw_fn = data.get("fieldnotes", {})
    fieldnotes = FieldnotesConfig(
        enabled=bool(raw_fn.get("enabled", False)),
        project=str(raw_fn.get("project", "")),
    )

    return Config(
        defaults=defaults,
        clusters=clusters,
        notifications=notifications,
        hosted=hosted,
        fieldnotes=fieldnotes,
    )
