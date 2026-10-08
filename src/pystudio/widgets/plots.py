"""The plot pane: figures the kernel published, drawn with the best protocol."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from textual import events
from textual.containers import Container, Vertical
from textual.message import Message
from textual.timer import Timer
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

RENDER_DELAY = 0.15
"""Wait for a zoom or a drag to pause before asking the kernel for a sharp render."""

RESIZE_DELAY = 0.2
"""Wait for a resize to finish before telling the kernel the new size."""

CELLS_PER_INCH = 5
"""A terminal line is about a fifth of an inch, which sets the size of a
figure laid out for the pane: its text then comes out near the terminal's."""

Size = tuple[float, float]
Window = tuple[float, float, float, float]

WHOLE: Window = (0.0, 0.0, 1.0, 1.0)


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
    figure_id: int | None = None
    """The kernel's handle on the figure, while it can still draw it again."""
    layout: Size | None = None
    """The size in inches ``png`` was laid out at, or ``None`` for the author's own."""
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
        ("a", "reflow", "lay out for the pane"),
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

    @dataclass
    class RenderRequested(Message):
        """The pane wants part of a figure drawn by the kernel, to fit ``room`` pixels."""

        figure: int
        room: tuple[int, int]
        window: Window
        size: Size | None

    @dataclass
    class Resized(Message):
        """The room for a figure changed, in pixels."""

        width: int
        height: int

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._figures: list[Figure] = []
        self._index = 0
        self._viewport = Viewport()
        self._source: PILImage.Image | None = None
        self._drag: tuple[int, int] | None = None
        self.reflow = False
        self._wanted: PlotsPane.RenderRequested | None = None
        self._render_timer: Timer | None = None
        self._resize_timer: Timer | None = None

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

    @property
    def room(self) -> tuple[int, int] | None:
        """The pixels there are for a figure, once the pane has been laid out."""
        if not self.stage.size.width or not self.stage.size.height:
            return None
        width, height = self._pane_pixels()
        return round(width), round(height)

    def add(self, png: bytes, *, title: str = "", figure_id: int | None = None) -> None:
        """Append a figure and show it.

        With ``figure_id`` the kernel kept the figure, and can draw it again.
        """
        self._figures.append(Figure(png, title=title, figure_id=figure_id))
        self._show(len(self._figures) - 1)

    def detach(self, figure_id: int | None = None) -> None:
        """Forget the kernel's handle on one figure, or on all of them.

        The figures stay, and zoom by enlarging the picture they arrived as.
        """
        for figure in self._figures:
            if figure_id is None or figure.figure_id == figure_id:
                figure.figure_id = None

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
        self._ask_kernel()

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

    # ---------------------------------------------------------------- sharp renders

    def _layout(self) -> Size | None:
        """The size, in inches, a figure laid out for the pane should have."""
        if not self.reflow:
            return None
        width, height = self._pane_pixels()
        dpi = get_cell_size().height * CELLS_PER_INCH
        return width / dpi, height / dpi

    def _ask_kernel(self) -> None:
        """Ask for the view on screen to be drawn at the pane's own resolution.

        What was just drawn is the picture already held, enlarged. That is on
        screen at once, and the kernel's render replaces it when it arrives.
        """
        if self._render_timer is not None:
            self._render_timer.stop()
            self._render_timer = None
        self._wanted = None
        figure, source = self.current, self._source
        if figure is None or source is None or figure.figure_id is None:
            return
        pane = self._pane_pixels()
        layout = self._layout()
        if figure.layout != layout:
            room, window = (round(pane[0]), round(pane[1])), WHOLE
        else:
            shown = self._viewport.shown(source.size, pane)
            room, window = (
                (round(shown[0]), round(shown[1])),
                self._viewport.window(source.size, pane),
            )
            if window == WHOLE and all(
                abs(have - want) <= max(2, want // 50)
                for have, want in zip(source.size, room, strict=True)
            ):
                return
        self._wanted = self.RenderRequested(figure.figure_id, room, window, layout)
        self._render_timer = self.set_timer(RENDER_DELAY, self._send_request)

    def _send_request(self) -> None:
        self._render_timer = None
        if self._wanted is not None:
            self.post_message(self._wanted)

    def show_render(self, request: RenderRequested, png: bytes | None) -> None:
        """Take the kernel's answer to ``request``; ``None`` means it had none.

        An answer to a view that has since moved on is dropped.
        """
        if request != self._wanted:
            return
        self._wanted = None
        figure = self.current
        if png is None or figure is None:
            return
        image = PILImage.open(BytesIO(png))
        image.load()
        if request.window == WHOLE:
            figure.png, figure.layout, self._source = png, request.size, image
        self._draw(image)

    def _caption(self) -> None:
        figure = self.current
        if figure is None:
            return
        parts = [f"{self._index + 1}/{len(self._figures)}"]
        if figure.title:
            parts.append(figure.title)
        if self._viewport.zoom > 1.0:
            parts.append(f"{self._viewport.zoom:.1f}×")
        if self.reflow and figure.figure_id is not None:
            parts.append("fills pane")
        parts.append(time.strftime("%H:%M", time.localtime(figure.created)))
        parts.append(PROTOCOL)
        self.caption.update(" · ".join(parts))

    def on_resize(self, event: events.Resize) -> None:
        if self.reflow:
            # The figure is about to be laid out again, so the old view means nothing.
            self._viewport.reset()
        self._render_current()
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(RESIZE_DELAY, self._announce_size)

    def _announce_size(self) -> None:
        self._resize_timer = None
        room = self.room
        if room is not None:
            self.post_message(self.Resized(*room))

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

    def action_reflow(self) -> None:
        """Switch between the figure as its author sized it and one that fills the pane."""
        self.reflow = not self.reflow
        self._viewport.reset()
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
        # Outside the stage is the border, which is a divider to drag.
        if self._viewport.zoom > 1.0 and self.stage.region.contains(event.screen_x, event.screen_y):
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
