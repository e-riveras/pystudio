"""Every figure of the session at once, to pick one or throw some away."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

from PIL import Image as PILImage
from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static
from textual_image.widget import Image

from pystudio.widgets.plots import Figure

COLUMNS = 4

THUMBNAIL = (480, 360)
"""Thumbnails are shrunk to this many pixels before they are drawn."""


class PlotGallery(ModalScreen[int | None]):
    """Modal grid of thumbnails. Enter shows the one under the cursor."""

    BINDINGS = [
        Binding("escape,q,g", "dismiss", "close"),
        Binding("enter", "choose", "show"),
        Binding("d", "delete", "delete"),
        Binding("h,left", "move(-1)", "left"),
        Binding("l,right", "move(1)", "right"),
        Binding("k,up", f"move(-{COLUMNS})", "up"),
        Binding("j,down", f"move({COLUMNS})", "down"),
    ]

    DEFAULT_CSS = f"""
    PlotGallery {{
        align: center middle;
        background: $background 60%;
    }}
    PlotGallery > #gallery-box {{
        width: 90%;
        height: 90%;
        border: round $accent;
        border-title-color: $accent;
        border-title-align: left;
        background: $surface;
    }}
    PlotGallery #gallery-grid {{
        grid-size: {COLUMNS};
        grid-rows: 12;
        height: auto;
    }}
    PlotGallery .card {{
        border: round $surface-lighten-2;
        align: center middle;
    }}
    PlotGallery .card.-chosen {{
        border: round $accent;
    }}
    PlotGallery .card Image {{
        width: auto;
        height: 1fr;
    }}
    PlotGallery .card Static {{
        height: 1;
        width: 100%;
        text-align: center;
        color: $text-muted;
    }}
    PlotGallery .card .page {{
        height: 1fr;
        content-align: center middle;
    }}
    PlotGallery #gallery-caption {{
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }}
    """

    def __init__(self, figures: list[Figure], cursor: int, delete: Callable[[int], None]) -> None:
        """``figures`` is the pane's own list, which ``delete`` removes from."""
        super().__init__()
        self._figures = figures
        self._cursor = cursor
        self._delete = delete

    def compose(self):
        with Vertical(id="gallery-box"):
            with VerticalScroll(), Grid(id="gallery-grid"):
                for index, figure in enumerate(self._figures):
                    with Vertical(classes="card"):
                        if figure.html is not None:
                            yield Static("interactive", classes="page")
                        else:
                            yield Image(self._thumbnail(figure))
                        yield Static(f"{index + 1} {figure.title}".strip())
            yield Static("enter shows · d deletes · escape closes", id="gallery-caption")

    @staticmethod
    def _thumbnail(figure: Figure) -> PILImage.Image:
        image = PILImage.open(BytesIO(figure.png))
        image.thumbnail(THUMBNAIL)
        return image

    def on_mount(self) -> None:
        self.query_one("#gallery-box").border_title = "plots"
        self._mark()

    @property
    def cursor(self) -> int:
        return self._cursor

    def _mark(self) -> None:
        for index, card in enumerate(self.query(".card")):
            card.set_class(index == self._cursor, "-chosen")
            if index == self._cursor:
                card.scroll_visible()

    def action_move(self, by: int) -> None:
        target = self._cursor + by
        if 0 <= target < len(self._figures):
            self._cursor = target
            self._mark()

    def action_choose(self) -> None:
        self.dismiss(self._cursor)

    async def action_delete(self) -> None:
        self._delete(self._cursor)
        if not self._figures:
            self.dismiss(None)
            return
        self._cursor = min(self._cursor, len(self._figures) - 1)
        await self.recompose()
        self._mark()
