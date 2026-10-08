"""The plot pane: what is on screen after a zoom, a pan or a key."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image as PILImage
from textual.app import App

from pystudio.widgets import plots as plots_module
from pystudio.widgets.plot_gallery import PlotGallery
from pystudio.widgets.plots import MAX_ZOOM, RENDER_DELAY, WHOLE, PlotsPane, Viewport, page_of

FIGURE = (640.0, 480.0)
PANE = (400.0, 400.0)


def png(size: tuple[int, int] = (64, 48), colour: str = "red") -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


class PlotsApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[PlotsPane.RenderRequested] = []
        self.forgotten: list[list[int] | None] = []
        self.exports: list[PlotsPane.ExportRequested] = []

    def compose(self):
        yield PlotsPane(id="plots")

    def on_plots_pane_render_requested(self, message: PlotsPane.RenderRequested) -> None:
        self.requests.append(message)

    def on_plots_pane_forgotten(self, message: PlotsPane.Forgotten) -> None:
        self.forgotten.append(message.figures)

    def on_plots_pane_export_requested(self, message: PlotsPane.ExportRequested) -> None:
        self.exports.append(message)

    @property
    def plots(self) -> PlotsPane:
        return self.query_one(PlotsPane)


# --------------------------------------------------------------------- the viewport


def test_a_fresh_viewport_shows_the_whole_figure() -> None:
    assert Viewport().window(FIGURE, PANE) == (0.0, 0.0, 1.0, 1.0)


def test_zooming_fills_the_pane_before_it_hides_anything() -> None:
    """A wide figure in a square pane has spare height to use up first."""
    view = Viewport()
    view.zoom_at(1.25, FIGURE, PANE)

    left, top, right, bottom = view.window(FIGURE, PANE)
    assert (top, bottom) == (0.0, 1.0)
    assert right - left == pytest.approx(0.8)
    assert view.shown(FIGURE, PANE) == pytest.approx((400.0, 375.0))


def test_zooming_keeps_the_point_under_the_pointer_still() -> None:
    view = Viewport()
    view.zoom_at(4.0, FIGURE, PANE)
    at = (0.25, 0.75)
    left, top, right, bottom = view.window(FIGURE, PANE)
    before = (left + at[0] * (right - left), top + at[1] * (bottom - top))

    view.zoom_at(2.0, FIGURE, PANE, at)

    left, top, right, bottom = view.window(FIGURE, PANE)
    after = (left + at[0] * (right - left), top + at[1] * (bottom - top))
    assert after == pytest.approx(before)


def test_zoom_stays_within_its_limits() -> None:
    view = Viewport()
    view.zoom_at(0.1, FIGURE, PANE)
    assert view.zoom == 1.0
    view.zoom_at(1e6, FIGURE, PANE)
    assert view.zoom == MAX_ZOOM


def test_panning_stops_at_the_edge_of_the_figure() -> None:
    view = Viewport()
    view.zoom_at(4.0, FIGURE, PANE)
    for _ in range(50):
        view.pan(1.0, 1.0, FIGURE, PANE)

    _, _, right, bottom = view.window(FIGURE, PANE)
    assert (right, bottom) == pytest.approx((1.0, 1.0))


def test_the_window_has_the_proportions_of_the_pane_once_zoomed_in() -> None:
    view = Viewport()
    view.zoom_at(8.0, FIGURE, PANE)

    assert view.shown(FIGURE, PANE) == pytest.approx(PANE)


# ------------------------------------------------------------------------- the pane


async def test_keys_zoom_pan_and_reset() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png())
        plots.focus()

        await pilot.press("+", "+")
        assert plots.viewport.zoom == pytest.approx(1.25**2)
        assert "1.6×" in str(plots.caption.content)

        await pilot.press("-")
        assert plots.viewport.zoom == pytest.approx(1.25)

        await pilot.press("+", "+", "+", "+")
        centre = plots.viewport.x
        await pilot.press("l")
        assert plots.viewport.x > centre

        await pilot.press("0")
        assert (plots.viewport.zoom, plots.viewport.x) == (1.0, 0.5)


async def test_the_figure_keeps_its_proportions_on_screen() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png((100, 100)))
        await pilot.pause()

        # Cells are twice as tall as wide, so a square takes twice the columns.
        image = plots.image_widget
        assert image.size.width == 2 * image.size.height


async def test_another_figure_starts_fitted() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png())
        plots.add(png(colour="blue"))
        plots.focus()

        await pilot.press("+", "[")

        assert plots.viewport.zoom == 1.0
        assert str(plots.caption.content).startswith("1/2")


async def test_f_fills_the_screen_and_gives_it_back() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png())
        plots.focus()

        await pilot.press("f")
        assert app.screen.maximized is plots
        await pilot.press("f")
        assert app.screen.maximized is None


async def test_the_wheel_zooms_and_a_drag_pans() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png())
        await pilot.pause()

        for _ in range(6):
            await pilot._post_mouse_events([_scroll_up()], plots, offset=(40, 10))
        assert plots.viewport.zoom > 1.0

        centre = plots.viewport.x
        await pilot.mouse_down(plots, offset=(40, 10))
        await pilot.hover(plots, offset=(30, 10))
        await pilot.mouse_up(plots, offset=(30, 10))
        assert plots.viewport.x > centre


def _scroll_up():
    from textual import events

    return events.MouseScrollUp


# -------------------------------------------------------------------- sharp renders


async def test_a_figure_the_kernel_kept_is_asked_for_at_the_size_on_screen() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png((64, 48)), figure_id=7)
        await pilot.pause(RENDER_DELAY * 2)

        (request,) = app.requests
        assert (request.figure, request.window, request.size) == (7, WHOLE, None)
        assert request.room[1] == plots.room[1]

        plots.show_render(request, png(request.room, "blue"))
        await pilot.pause(RENDER_DELAY * 2)

        # The picture held now is the sharp one, so there is nothing left to ask.
        assert plots.current.png == png(request.room, "blue")
        assert len(app.requests) == 1


async def test_a_plain_picture_is_never_asked_for() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.plots.add(png())
        app.plots.focus()
        await pilot.press("+")
        await pilot.pause(RENDER_DELAY * 2)

        assert app.requests == []


async def test_a_burst_of_zooming_asks_once_and_drops_the_stale_answer() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png(plots.room), figure_id=1)
        plots.focus()
        await pilot.press("+", "+", "+")
        await pilot.pause(RENDER_DELAY * 2)

        (request,) = app.requests
        assert request.window != WHOLE

        await pilot.press("+")
        shown = plots.image_widget.image
        plots.show_render(request, png(request.room, "blue"))
        assert plots.image_widget.image is shown


async def test_a_lays_the_figure_out_for_the_pane() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png(plots.room), figure_id=1)
        plots.focus()
        await pilot.press("a")
        await pilot.pause(RENDER_DELAY * 2)

        (request,) = app.requests
        assert request.room == plots.room
        assert request.size == pytest.approx((plots.room[0] / 100, plots.room[1] / 100))

        plots.show_render(request, png(request.room))
        assert plots.current.layout == request.size


async def test_a_detached_figure_still_zooms() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png(plots.room), figure_id=1)
        plots.detach()
        plots.focus()
        await pilot.press("+")
        await pilot.pause(RENDER_DELAY * 2)

        assert plots.viewport.zoom > 1.0
        assert app.requests == []


# --------------------------------------------------------------------- the history


async def test_d_deletes_and_shift_d_clears() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png(), figure_id=1)
        plots.add(png(), figure_id=2)
        plots.add(png())
        plots.focus()

        await pilot.press("[", "d")
        assert plots.count == 2
        assert app.forgotten == [[2]]
        assert str(plots.caption.content).startswith("2/2")

        await pilot.press("D")
        assert plots.count == 0
        assert app.forgotten == [[2], None]
        assert str(plots.caption.content) == "no plots yet"
        assert not plots.image_widget.display


async def test_an_update_takes_the_place_of_the_figure_it_names() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)):
        plots = app.plots
        plots.add(png(), display_id="live")
        plots.add(png())

        plots.add(png(colour="blue"), display_id="live", update=True)

        assert plots.count == 2
        assert plots.figures[0].png == png(colour="blue")
        assert str(plots.caption.content).startswith("2/2")


async def test_an_interactive_figure_opens_in_the_browser(monkeypatch) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(plots_module, "launch", lambda path: opened.append(path) or True)
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add_page("<div></div><script>draw()</script>")
        plots.focus()
        await pilot.pause()

        assert "interactive" in str(plots.caption.content)
        assert plots.query_one("#plot-note").display

        # There is no picture to zoom, and that is not an error.
        await pilot.press("+", "l", "o")
        (page,) = opened
        assert page.suffix == ".html" and "draw()" in page.read_text()


def test_only_output_with_a_script_counts_as_a_figure() -> None:
    assert page_of({"text/html": "<table><tr><td>1</td></tr></table>"}) is None
    assert page_of({"text/plain": "3"}) is None
    assert page_of({"text/html": "<div id='v'></div><script>embed()</script>"}) is not None

    page = page_of({plots_module.PLOTLY: {"data": [{"y": [1, 2]}], "layout": {}}})
    assert page is not None and '"y": [1, 2]' in page and "Plotly.newPlot" in page


async def test_ctrl_s_saves_what_is_shown(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.plots.add(png())
        app.plots.focus()
        await pilot.press("ctrl+s")

        (saved,) = tmp_path.glob("plot-*.png")
        assert saved.read_bytes() == png()


async def test_a_vector_is_asked_of_the_kernel_only_when_it_has_the_figure() -> None:
    app = PlotsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        plots = app.plots
        plots.add(png())
        plots.add(png(plots.room), figure_id=4)
        plots.focus()

        await pilot.press("S")
        await pilot.pause()
        assert [(request.figure, request.fmt) for request in app.exports] == [(4, "svg")]

        await pilot.press("[", "P")
        await pilot.pause()
        assert len(app.exports) == 1
        assert "pdf" in str(plots.caption.content)


async def test_the_gallery_picks_and_deletes() -> None:
    app = PlotsApp()
    async with app.run_test(size=(120, 40)) as pilot:
        plots = app.plots
        for colour in ("red", "green", "blue"):
            plots.add(png(colour=colour))
        plots.focus()

        await pilot.press("g")
        gallery = app.screen
        assert isinstance(gallery, PlotGallery) and gallery.cursor == 2

        await pilot.press("h", "d")
        assert plots.count == 2
        assert [figure.png for figure in plots.figures] == [png(colour="red"), png(colour="blue")]

        await pilot.press("h", "enter")
        assert not isinstance(app.screen, PlotGallery)
        assert str(plots.caption.content).startswith("1/2")
