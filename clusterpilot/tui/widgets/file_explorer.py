"""Left-sidebar file explorer — DirectoryTree with smart path navigation."""
from __future__ import annotations

import json
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.message import Message
from textual.suggester import Suggester
from textual.widget import Widget
from textual.widgets import DirectoryTree, Input, Label

_RECENT_FILE = Path.home() / ".config" / "clusterpilot" / "recent_paths.json"
_MAX_RECENT = 8


def load_recent_paths() -> list[Path]:
    try:
        items = json.loads(_RECENT_FILE.read_text())
        return [Path(p) for p in items if Path(p).is_dir()]
    except Exception:
        return []


def save_recent_path(path: Path) -> None:
    """Prepend *path* to the recent-paths list and persist."""
    resolved = path.expanduser().resolve()
    recent = [p for p in load_recent_paths() if p != resolved]
    recent.insert(0, resolved)
    recent = recent[:_MAX_RECENT]
    try:
        _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(json.dumps([str(p) for p in recent]))
    except OSError:
        pass


class _PathSuggester(Suggester):
    """Tab-completes directory paths.

    When the input is empty, suggests the most recently used path so the
    user can jump straight back to their last project with a single Tab.
    """

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            recent = load_recent_paths()
            if recent:
                return str(recent[0]) + "/"
            return str(Path.home()) + "/"

        try:
            expanded = Path(value).expanduser()
            directory = expanded if value.endswith("/") else expanded.parent
            prefix = "" if value.endswith("/") else expanded.name

            if not directory.is_dir():
                return None

            matches = sorted(
                e for e in directory.iterdir()
                if e.is_dir() and e.name.startswith(prefix)
            )
            if not matches:
                return None

            result = str(matches[0]) + "/"
            if value.startswith("~"):
                home = str(Path.home())
                if result.startswith(home):
                    result = "~" + result[len(home):]
            return result

        except (PermissionError, ValueError, OSError):
            return None


class FileExplorer(Widget):
    """Amber-phosphor file-explorer sidebar.

    Posts ``FileExplorer.FileSelected`` when the user clicks a file in the
    tree. Clicking a directory updates the path bar but does not post a
    message — directory navigation is internal to this widget.

    Opens at the most recently used project directory (persisted across
    sessions). Falls back to ``~`` on first launch.
    """

    class FileSelected(Message):
        """A file was clicked in the tree."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Label("═ FILES ", id="explorer-title")
        yield Input(
            placeholder="~/path  (Tab ↹ complete · Enter navigate)",
            id="explorer-path-input",
            suggester=_PathSuggester(),
        )
        yield DirectoryTree(str(Path.home()), id="explorer-tree")

    def on_mount(self) -> None:
        recent = load_recent_paths()
        root = recent[0] if recent else Path.home()
        self._set_root(root, update_input=True)

    # ── Internal navigation ───────────────────────────────────────────────────

    def _set_root(self, path: Path, *, update_input: bool = False) -> None:
        """Point the DirectoryTree at *path* (must be a directory)."""
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            resolved = resolved.parent
        tree = self.query_one("#explorer-tree", DirectoryTree)
        tree.path = resolved
        if update_input:
            inp = self.query_one("#explorer-path-input", Input)
            inp.value = str(resolved)

    @on(Input.Submitted, "#explorer-path-input")
    def _on_path_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if not val:
            return
        p = Path(val).expanduser()
        if p.is_dir():
            self._set_root(p, update_input=True)
            save_recent_path(p)
        else:
            self.app.notify(f"Not a directory: {val}", severity="warning")

    # ── Tree events ───────────────────────────────────────────────────────────

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Update the path bar as the user browses — navigation feedback."""
        event.stop()
        inp = self.query_one("#explorer-path-input", Input)
        inp.value = str(event.path)

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        event.stop()
        self.post_message(self.FileSelected(event.path))
