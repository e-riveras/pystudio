"""The shell: panes wired to a real Neovim and a real kernel."""

from __future__ import annotations

import asyncio
import base64
import io
import shutil
import time

import pytest
from PIL import Image as PILImage

from pystudio import messages as m
from pystudio.app import PyStudioApp
from pystudio.widgets import ConsolePane, NvimPane, VariablesPane

pytestmark = pytest.mark.skipif(shutil.which("nvim") is None, reason="nvim is not installed")

SIZE = (100, 30)


def transcript(app: PyStudioApp) -> str:
    """Everything the console has printed, as plain text."""
    lines = app.console_pane.log_widget.lines
    return "\n".join("".join(segment.text for segment in line) for line in lines)


def names(table: VariablesPane) -> set[str]:
    return {str(row.value) for row in table.rows}


async def until(predicate, *, timeout: float = 30.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{what} never became true within {timeout}s")


def app_with(tmp_path, **kwargs) -> PyStudioApp:
    return PyStudioApp(clean=True, **kwargs)


async def test_editor_shows_a_live_neovim(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE):
        editor = app.query_one("#editor", NvimPane)
        await until(
            lambda: (
                (editor.grid.width, editor.grid.height) == (editor.size.width, editor.size.height)
            ),
            what="a grid matching the pane",
        )
        assert editor.channel > 0


async def test_keys_reach_neovim_untouched(tmp_path) -> None:
    """The chord keys must not steal `1`, `q` or `i` from the editor."""
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        editor = app.query_one("#editor", NvimPane)
        await until(lambda: editor.channel > 0, what="an attached grid")

        await pilot.press("i", "1", "q", "z", "escape")
        await until(
            lambda: editor.grid.row_text(0).startswith("1qz"),
            what="typed text in the buffer",
        )


async def test_chord_moves_focus(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app.query_one("#editor", NvimPane).channel > 0)
        assert isinstance(app.focused, NvimPane)

        await pilot.press("ctrl+g", "2")
        assert app.focused is not None
        assert isinstance(app.focused.parent, ConsolePane)

        await pilot.press("ctrl+g", "3")
        assert isinstance(app.focused, VariablesPane)


async def test_chord_is_cancelled_by_a_plain_key(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        editor = app.query_one("#editor", NvimPane)
        await until(lambda: editor.channel > 0)

        await pilot.press("ctrl+g")
        assert app._chord is True
        await pilot.press("x")  # goes to Neovim, and clears the chord
        assert app._chord is False


async def test_sending_a_line_runs_it_and_updates_the_variables(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE):
        editor = app.query_one("#editor", NvimPane)
        await until(lambda: editor.channel > 0)
        await until(lambda: app._kernel_ready, what="a running kernel")

        await editor.rpc.request("nvim_buf_set_lines", 0, 0, -1, False, ["value = 7"])
        await editor.rpc.request("nvim_exec_lua", "pystudio.send_line()", [])

        await until(lambda: "value = 7" in transcript(app), what="the echo in the console")
        await until(lambda: "value" in names(app.variables), what="the variable in the table")


async def test_console_prompt_executes(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")

        app.console_pane.prompt.focus()
        await pilot.press(*"6 * 7")
        await pilot.press("enter")

        await until(lambda: "42" in transcript(app), what="the result in the console")


async def test_console_waits_for_an_unfinished_block(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")

        app.console_pane.prompt.focus()
        await pilot.press(*"for i in range(2):")
        await pilot.press("enter")
        assert "for i in range(2):" not in transcript(app)

        await pilot.press(*"    print(i)")
        await pilot.press("enter")
        await pilot.press("enter")  # an empty line ends the block

        await until(lambda: "0\n1" in transcript(app), what="both loop iterations")


async def test_traceback_reaches_the_console(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")

        app.console_pane.prompt.focus()
        await pilot.press(*"1 / 0")
        await pilot.press("enter")

        await until(lambda: "ZeroDivisionError" in transcript(app), what="the traceback")


async def test_png_display_data_lands_in_the_plot_pane(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE):
        buffer = io.BytesIO()
        PILImage.new("RGB", (8, 8), "red").save(buffer, format="PNG")
        payload = base64.b64encode(buffer.getvalue()).decode()

        app.post_message(m.DisplayData(data={"image/png": payload}))
        await until(lambda: app.plots.count == 1, what="a figure in the plot pane")
