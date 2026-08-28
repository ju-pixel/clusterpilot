"""Modal confirmation dialogue for destructive actions.

One screen for every irreversible thing the TUI can do. The body text must
name the target, so the user reads what is about to happen rather than
trusting the button they pressed.

Styling lives in the app's CSS string (``tui/app.py``) alongside the rest of
the phosphor-amber palette: the palette variables are declared there, and
Textual scopes CSS variables to the source that declares them, so a
``DEFAULT_CSS`` here could not refer to ``$amber`` and friends.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmScreen(ModalScreen[bool]):
    """Ask the user to confirm, dismissing with True or False.

    Keyboard only: ``y`` confirms, ``n`` or ``escape`` cancels, and the
    CANCEL button holds the initial focus so a stray Enter is harmless.
    """

    BINDINGS = [
        Binding("y", "confirm", "Confirm", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-panel"):
            yield Label(self._title, id="confirm-title")
            # markup=False: bodies carry cluster paths, which may contain
            # square brackets that Rich would try to read as markup.
            yield Static(self._body, id="confirm-body", markup=False)
            with Horizontal(id="confirm-actions"):
                # Escaped brackets: button labels are parsed as markup.
                yield Button(r"\[Y] CONFIRM", id="btn-confirm")
                yield Button(r"\[N] CANCEL", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#btn-cancel", Button).focus()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "btn-confirm")
