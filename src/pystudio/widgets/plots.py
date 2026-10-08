"""The plot pane: figures the kernel published, drawn with the best protocol."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from textual import events
from textual.containers import Container, Vertical
from textual.widgets import Static
from textual_image._terminal import get_cell_size
from textual_image.renderable import Image as AutoRenderable
from textual_image.widget import Image

PROTOCOL = AutoRenderable.__module__.rsplit(".", 1)[-1]
"""``tgp``, ``sixel``, ``halfcell`` or ``unicode``, decided by the terminal."""

ZOOM_STEP = 1.25
"""How much one key press or wheel notch zooms."""

MAX_ZOOM = 32.0

PAN_STEP = 0.2
"""How far one key press pans, as a fraction of what is on screen."""

Size = tuple[float, float]
Window = tuple[float, float, float, float]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


@dataclass
class Viewport:
    """Which part of a figure is on screen: a zoom factor and the point at the centre.

    The centre is in fractions of the figure, so it survives a resize and a
    render at another resolution. At zoom 1 the whole figure fits the pane. Past
    that the window first grows to fill the pane, and only then hides anything.
    """

    zoom: float = 1.0
    x: float = 0.5
    y: float = 0.5

    def scale(self, figure: Size, pane: Size) -> float:
        """Screen pixels per figure pixel."""
        return min(pane[0] / figure[0], pane[1] / figure[1]) * self.zoom

    def extent(self, figure: Size, pane: Size) -> Size:
        """The fraction of the figure that is visible along each axis."""
        scale = self.scale(figure, pane)
        return (
            min(1.0, pane[0] / (figure[0] * scale)),
            min(1.0, pane[1] / (figure[1] * scale)),
        )

    def window(self, figure: Size, pane: Size) -> Window:
        """The visible part as ``left, top, right, bottom`` fractions of the figure."""
        width, height = self.extent(figure, pane)
        left = _clamp(self.x - width / 2, 0.0, 1.0 - width)
        top = _clamp(self.y - height / 2, 0.0, 1.0 - height)
        return left, top, left + width, top + height

    def shown(self, figure: Size, pane: Size) -> Size:
        """The size the visible part takes on screen, in pixels."""
        scale = self.scale(figure, pane)
        width, height = self.extent(figure, pane)
        return width * figure[0] * scale, height * figure[1] * scale

    def zoom_at(self, factor: float, figure: Size, pane: Size, at: Size = (0.5, 0.5)) -> None:
        """Zoom by ``factor``, keeping the point at ``at`` (fractions of the window) still."""
        left, top, right, bottom = self.window(figure, pane)
        anchor_x = left + at[0] * (right - left)
        anchor_y = top + at[1] * (bottom - top)
        self.zoom = _clamp(self.zoom * factor, 1.0, MAX_ZOOM)
        width, height = self.extent(figure, pane)
        self.x = anchor_x - at[0] * width + width / 2
        self.y = anchor_y - at[1] * height + height / 2
        self._settle(figure, pane)

    def pan(self, dx: float, dy: float, figure: Size, pane: Size) -> None:
        """Move by a fraction of the window; positive is right and down."""
        width, height = self.extent(figure, pane)
        self.x += dx * width
        self.y += dy * height
        self._settle(figure, pane)

    def reset(self) -> None:
        self.zoom, self.x, self.y = 1.0, 0.5, 0.5

    def _settle(self, figure: Size, pane: Size) -> None:
        """Keep the centre where the window does not run off the figure."""
        width, height = self.extent(figure, pane)
        self.x = _clamp(self.x, width / 2, 1.0 - width / 2)
        self.y = _clamp(self.y, height / 2, 1.0 - height / 2)


@dataclass
class Figure:
    """One entry of the plot history."""

    png: bytes
    title: str = ""
    created: float = field(default_factory=time.time)


class PlotsPane(Vertical):
    """Holds every figure of the session and shows one at a time."""

    BINDINGS = [
        ("[", "previous", "previous plot"),
        ("]", "next", "next plot"),
        ("plus,equals_sign", "zoom(1)", "zoom in"),
        ("minus", "zoom(-1)", "zoom out"),
        ("0", "reset", "fit"),
        ("h,left", "pan(-1, 0)", "pan left"),
        ("l,right", "pan(1, 0)", "pan right"),
        ("k,up", "pan(0, -1)", "pan up"),
        ("j,down", "pan(0, 1)", "pan down"),
        ("f,enter", "fullscreen", "fullscreen"),
        ("ctrl+s", "save", "save plot"),
    ]

    DEFAULT_CSS = """
    PlotsPane {
        layout: vertical;
    }
    PlotsPane > #plot-stage {
        height: 1fr;
        width: 1fr;
        align: center middle;
    }
    PlotsPane > #plot-caption {
        height: 1;
        color: $text-muted;
    }
    """

    can_focus = True

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._figures: list[Figure] = []
        self._index = 0
        self._viewport = Viewport()
        self._source: PILImage.Image | None = None
        self._drag: tuple[int, int] | None = None

    def compose(self):
        with Container(id="plot-stage"):
            yield Image(id="plot-image")
        yield Static("no plots yet", id="plot-caption")

    @property
    def image_widget(self) -> Image:
        return self.query_one("#plot-image", Image)

    @property
    def stage(self) -> Container:
        return self.query_one("#plot-stage", Container)

    @property
    def caption(self) -> Static:
        return self.query_one("#plot-caption", Static)

    @property
    def count(self) -> int:
        return len(self._figures)

    @property
    def current(self) -> Figure | None:
        return self._figures[self._index] if self._figures else None

    @property
    def viewport(self) -> Viewport:
        return self._viewport

    def add(self, png: bytes, *, title: str = "") -> None:
        """Append a figure and show it."""
        self._figures.append(Figure(png, title=title))
        self._show(len(self._figures) - 1)

    def _show(self, index: int) -> None:
        """Move to another figure, which starts fitted to the pane."""
        self._index = index
        self._viewport.reset()
        self._source = PILImage.open(BytesIO(self._figures[index].png))
        self._source.load()
        self._render_current()

    # ---------------------------------------------------------------------- drawing

    def _pane_pixels(self) -> Size:
        """The room there is for the figure, in pixels."""
        cell = get_cell_size()
        room = self.stage.size
        return max(room.width, 1) * cell.width, max(room.height, 1) * cell.height

    def _render_current(self) -> None:
        figure, source = self.current, self._source
        if figure is None or source is None:
            self.caption.update("no plots yet")
            return
        pane = self._pane_pixels()
        width, height = source.size
        left, top, right, bottom = self._viewport.window(source.size, pane)
        box = (
            round(left * width),
            round(top * height),
            max(round(right * width), round(left * width) + 1),
            max(round(bottom * height), round(top * height) + 1),
        )
        self._draw(source if box == (0, 0, width, height) else source.crop(box))
        self._caption()

    def _draw(self, view: PILImage.Image) -> None:
        """Put ``view`` on screen at the size the viewport gives it.

        The image widget stretches to whatever cells it is given, so the cells
        are worked out here to keep the figure's proportions.
        """
        assert self._source is not None
        cell = get_cell_size()
        room = self.stage.size
        shown = self._viewport.shown(self._source.size, self._pane_pixels())
        image = self.image_widget
        image.styles.width = int(_clamp(round(shown[0] / cell.width), 1, max(room.width, 1)))
        image.styles.height = int(_clamp(round(shown[1] / cell.height), 1, max(room.height, 1)))
        image.image = view

    def _caption(self) -> None:
        figure = self.current
        if figure is None:
            return
        parts = [f"{self._index + 1}/{len(self._figures)}"]
        if figure.title:
            parts.append(figure.title)
        if self._viewport.zoom > 1.0:
            parts.append(f"{self._viewport.zoom:.1f}×")
        parts.append(time.strftime("%H:%M", time.localtime(figure.created)))
        parts.append(PROTOCOL)
        self.caption.update(" · ".join(parts))

    def on_resize(self, event: events.Resize) -> None:
        self._render_current()

    # ---------------------------------------------------------------------- actions

    def action_previous(self) -> None:
        if self._figures:
            self._show((self._index - 1) % len(self._figures))

    def action_next(self) -> None:
        if self._figures:
            self._show((self._index + 1) % len(self._figures))

    def action_zoom(self, direction: int) -> None:
        self._zoom(ZOOM_STEP if direction > 0 else 1 / ZOOM_STEP)

    def action_reset(self) -> None:
        self._viewport.reset()
        self._render_current()

    def action_pan(self, dx: int, dy: int) -> None:
        if self._source is None:
            return
        self._viewport.pan(dx * PAN_STEP, dy * PAN_STEP, self._source.size, self._pane_pixels())
        self._render_current()

    def action_fullscreen(self) -> None:
        screen = self.screen
        if screen.maximized is self:
            screen.minimize()
        else:
            screen.maximize(self, container=False)

    def action_save(self) -> None:
        figure = self.current
        if figure is None:
            return
        target = Path.cwd() / f"plot-{time.strftime('%Y%m%d-%H%M%S')}.png"
        target.write_bytes(figure.png)
        self.caption.update(f"saved {target.name}")

    def _zoom(self, factor: float, at: Size = (0.5, 0.5)) -> None:
        if self._source is None:
            return
        self._viewport.zoom_at(factor, self._source.size, self._pane_pixels(), at)
        self._render_current()

    # ------------------------------------------------------------------------ mouse

    def _pointer(self, event: events.MouseEvent) -> Size:
        """Where the pointer is, in fractions of the figure on screen."""
        region = self.image_widget.region
        if not region.width or not region.height:
            return 0.5, 0.5
        return (
            _clamp((event.screen_x - region.x + 0.5) / region.width, 0.0, 1.0),
            _clamp((event.screen_y - region.y + 0.5) / region.height, 0.0, 1.0),
        )

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self._zoom(ZOOM_STEP, self._pointer(event))

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self._zoom(1 / ZOOM_STEP, self._pointer(event))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.focus()
        if self._viewport.zoom > 1.0:
            self._drag = (event.screen_x, event.screen_y)
            self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag is None or self._source is None:
            return
        region = self.image_widget.region
        if not region.width or not region.height:
            return
        # Dragging moves the figure, so the window goes the other way.
        self._viewport.pan(
            (self._drag[0] - event.screen_x) / region.width,
            (self._drag[1] - event.screen_y) / region.height,
            self._source.size,
            self._pane_pixels(),
        )
        self._drag = (event.screen_x, event.screen_y)
        self._render_current()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag is not None:
            self._drag = None
            self.release_mouse()

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2:
            self.action_fullscreen()
