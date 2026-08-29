"""F9 CONFIG view — config display with in-editor editing."""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static

from clusterpilot.config import CONFIG_PATH, ConfigError, load_config
from clusterpilot.ssh.connection import _CONTROL_PATH

if TYPE_CHECKING:
    from clusterpilot.tui.app import ClusterPilotApp


def _row(key: str, value: str) -> str:
    return f"[#7a6a50]{key:<20}[/] [#f0e8d0]{value}[/]\n"


def _render(app: "ClusterPilotApp") -> str:
    cfg = app._config
    lines: list[str] = []

    for profile in cfg.clusters:
        lines.append(f"[bold #e8a020]CLUSTER — {profile.name.upper()}[/]\n")
        lines.append(_row("Host",    profile.host))
        lines.append(_row("User",    profile.user))
        lines.append(_row("Account", profile.account))
        lines.append(_row("Scratch", profile.expand_scratch()))
        # The cluster type drives every quirk in the generated script, so an
        # inferred one is called out: it is a guess from the hostname, not a
        # setting, and a wrong guess is worth catching here rather than at sbatch.
        type_display = profile.cluster_type
        if profile.inferred_cluster_type:
            type_display = f"{type_display} [#e05050](inferred, set cluster_type)[/]"
        lines.append(_row("Type", type_display))
        lines.append("\n")

    # Only values ClusterPilot actually uses belong here: the ControlPath is
    # read from the SSH layer so the two can never drift apart.
    lines.append("[bold #e8a020]SSH[/]\n")
    lines.append(_row("ControlPath", _CONTROL_PATH))
    lines.append("\n")

    lines.append("[bold #e8a020]NOTIFICATIONS[/]\n")
    n = cfg.notifications
    lines.append(_row("Backend",     n.backend))
    lines.append(_row("ntfy topic",  n.ntfy_topic or "[#7a6a50](not set)[/]"))
    lines.append(_row("ntfy server", n.ntfy_server))
    # The URL a notification is actually POSTed to, so a doubled topic or a
    # stray path is visible without reading the config file.
    lines.append(_row("Notify URL", n.resolved_url or "[#7a6a50](no topic set)[/]"))
    lines.append("\n")

    lines.append("[bold #e8a020]AI SCRIPT GENERATION[/]\n")
    lines.append(_row("Provider", cfg.provider))
    lines.append(_row("Model", cfg.model))
    if cfg.provider == "ollama":
        api_display = "[#7a6a50](not required for ollama)[/]"
    elif cfg.hosted.api_token:
        api_display = "[#7a6a50](using managed key — see Hosted tier below)[/]"
    elif cfg.api_key:
        api_display = f"[#7a6a50]{cfg.api_key[:8]}…[/]"
    else:
        env_var = "OPENAI_API_KEY" if cfg.provider == "openai" else "ANTHROPIC_API_KEY"
        api_display = f"[#e05050](not set — export {env_var})[/]"
    lines.append(f"[#7a6a50]{'API key':<20}[/] {api_display}\n")
    if cfg.api_base_url:
        lines.append(_row("Base URL", cfg.api_base_url))
    lines.append(_row("Poll interval", f"{cfg.poll_interval}s"))
    lines.append("\n")

    lines.append("[bold #e8a020]HOSTED TIER[/]\n")
    lines.append(_row("API URL", cfg.hosted.api_url))
    if cfg.hosted.api_token:
        masked = cfg.hosted.api_token[:6] + "…"
        lines.append(_row("Token", f"[#7a6a50]{masked}[/] [#6ed86e](active)[/]"))
    else:
        lines.append(
            f"[#7a6a50]{'Token':<20}[/] [#7a6a50](not set — issue one from the dashboard)[/]\n"
        )

    return "".join(lines)


class ConfigView(Static):
    """Scrollable config display with an open-in-editor button."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="config-scroll"):
            yield Static(id="config-content")
        with Horizontal(id="config-actions"):
            yield Button("✎  EDIT CONFIG", id="btn-edit-config")

    def on_mount(self) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        app = cast("ClusterPilotApp", self.app)
        self.query_one("#config-content", Static).update(_render(app))

    @on(Button.Pressed, "#btn-edit-config")
    def on_edit_config(self) -> None:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        with self.app.suspend():
            subprocess.run([editor, str(CONFIG_PATH)])
        # Reload config and refresh display after editor closes.
        app = cast("ClusterPilotApp", self.app)
        try:
            app._config = load_config()
            self._refresh_display()
            self.app.notify("Config reloaded.", severity="information")
        except ConfigError as exc:
            self.app.notify(f"Config error: {exc}", severity="error", markup=False)
