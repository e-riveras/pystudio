"""The plot pane: what is on screen after a zoom, a pan or a key."""

from __future__ import annotations

import io

import pytest
from PIL import Image as PILImage
from textual.app import App

from pystudio.widgets.plots import MAX_ZOOM, PlotsPane, Viewport

FIGURE = (640.0, 480.0)
PANE = (400.0, 400.0)


def png(size: tuple[int, int] = (64, 48), colour: str = "red") -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


class PlotsApp(App):
    def compose(self):
        yield PlotsPane(id="plots")

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
