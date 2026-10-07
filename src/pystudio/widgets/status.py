"""One line at the bottom: kernel state, kernel, file, image protocol."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.widgets import Static

STATE_STYLES = {
    "starting": "yellow",
    "restarting": "yellow",
    "busy": "bold yellow",
    "idle": "green",
    "dead": "bold red",
}


class StatusBar(Static):
    """Plain text, rebuilt whenever one of its parts changes."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, *, kernel_name: str = "python3", protocol: str = "", id: str | None = None):
        super().__init__(id=id)
        self.state = "starting"
        self.kernel_name = kernel_name
        self.protocol = protocol
        self.filename = ""
        self.note = ""

    def on_mount(self) -> None:
        self.redraw()

    def set_state(self, state: str) -> None:
        self.state = state
        self.redraw()

    def set_kernel(self, kernel_name: str) -> None:
        self.kernel_name = kernel_name
        self.redraw()

    def set_filename(self, path: str) -> None:
        self.filename = Path(path).name if path else ""
        self.redraw()

    def set_note(self, note: str) -> None:
        self.note = note
        self.redraw()

    def redraw(self) -> None:
        line = Text()
        line.append("kernel: ", style="dim")
        line.append(self.state, style=STATE_STYLES.get(self.state, "default"))
        for part in (self.kernel_name, self.filename, self.protocol, self.note):
            if part:
                line.append(" · ", style="dim")
                line.append(part)
        self.update(line)
