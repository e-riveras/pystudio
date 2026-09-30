"""The plot pane: figures the kernel published, drawn with the best protocol."""

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from textual.containers import Vertical
from textual.widgets import Static
from textual_image.renderable import Image as AutoRenderable
from textual_image.widget import Image

PROTOCOL = AutoRenderable.__module__.rsplit(".", 1)[-1]
"""``tgp``, ``sixel``, ``halfcell`` or ``unicode``, decided by the terminal."""


class PlotsPane(Vertical):
    """Holds every figure of the session and shows one at a time."""

    BINDINGS = [
        ("[", "previous", "previous plot"),
        ("]", "next", "next plot"),
        ("ctrl+s", "save", "save plot"),
    ]

    DEFAULT_CSS = """
    PlotsPane {
        layout: vertical;
    }
    PlotsPane > Image {
        height: 1fr;
        width: 1fr;
    }
    PlotsPane > #plot-caption {
        height: 1;
        color: $text-muted;
    }
    """

    can_focus = True

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._figures: list[bytes] = []
        self._index = 0

    def compose(self):
        yield Image(id="plot-image")
        yield Static("no plots yet", id="plot-caption")

    @property
    def image_widget(self) -> Image:
        return self.query_one("#plot-image", Image)

    @property
    def caption(self) -> Static:
        return self.query_one("#plot-caption", Static)

    @property
    def count(self) -> int:
        return len(self._figures)

    def add(self, png: bytes) -> None:
        """Append a figure and show it."""
        self._figures.append(png)
        self._index = len(self._figures) - 1
        self._render_current()

    def _render_current(self) -> None:
        if not self._figures:
            self.caption.update("no plots yet")
            return
        png = self._figures[self._index]
        self.image_widget.image = PILImage.open(BytesIO(png))
        self.caption.update(f"{self._index + 1}/{len(self._figures)} · {PROTOCOL}")

    def action_previous(self) -> None:
        if self._figures:
            self._index = (self._index - 1) % len(self._figures)
            self._render_current()

    def action_next(self) -> None:
        if self._figures:
            self._index = (self._index + 1) % len(self._figures)
            self._render_current()

    def action_save(self) -> None:
        if not self._figures:
            return
        target = Path.cwd() / f"plot-{time.strftime('%Y%m%d-%H%M%S')}.png"
        target.write_bytes(self._figures[self._index])
        self.caption.update(f"saved {target.name}")
