"""F9 CONFIG view — read-only display of loaded configuration."""
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static

if TYPE_CHECKING:
    from clusterpilot.tui.app import ClusterPilotApp


def _row(key: str, value: str) -> str:
    return f"[#7a6a50]{key:<20}[/] [#f0e8d0]{value}[/]\n"


class ConfigView(Static):
    """Scrollable read-only config display."""

    def compose(self) -> ComposeResult:
        yield Static(id="config-content")

    def on_mount(self) -> None:
        app = cast("ClusterPilotApp", self.app)
        cfg = app._config
        lines: list[str] = []

        # Cluster profiles
        for profile in cfg.clusters:
            lines.append(f"[bold #e8a020]CLUSTER — {profile.name.upper()}[/]\n")
            lines.append(_row("Host",    profile.host))
            lines.append(_row("User",    profile.user))
            lines.append(_row("Account", profile.account))
            lines.append(_row("Scratch", profile.expand_scratch()))
            lines.append("\n")

        # SSH strategy note
        lines.append("[bold #e8a020]SSH[/]\n")
        lines.append(_row("Strategy",     "ControlMaster auto"))
        lines.append(_row("ControlPath",  "~/.ssh/cm_%h_%p_%r"))
        lines.append(_row("ControlPersist", "4h"))
        lines.append("\n")

        # Notifications
        lines.append("[bold #e8a020]NOTIFICATIONS[/]\n")
        n = cfg.notifications
        lines.append(_row("Backend",     n.backend))
        lines.append(_row("ntfy topic",  n.ntfy_topic or "[#7a6a50](not set)[/]"))
        lines.append(_row("ntfy server", n.ntfy_server))
        lines.append("\n")

        # AI / defaults
        lines.append("[bold #e8a020]AI SCRIPT GENERATION[/]\n")
        lines.append(_row("Model",         cfg.model))
        api_display = (
            f"[#7a6a50]{cfg.api_key[:8]}…[/]"
            if cfg.api_key else "[#e05050](not set — export ANTHROPIC_API_KEY)[/]"
        )
        lines.append(f"[#7a6a50]{'API key':<20}[/] {api_display}\n")
        lines.append(_row("Poll interval", f"{cfg.poll_interval}s"))

        self.query_one("#config-content", Static).update("".join(lines))
