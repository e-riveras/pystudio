"""The shell: panes wired to a real Neovim and a real kernel."""

from __future__ import annotations

import asyncio
import base64
import io
import shutil
import sys
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage

from pystudio import messages as m
from pystudio.app import PyStudioApp
from pystudio.assistant.provider import TextDelta, ToolCall, TurnEnd
from pystudio.interpreter import KernelChoice
from pystudio.widgets import (
    ConsolePane,
    FrameViewer,
    KernelPicker,
    NvimPane,
    VariablesPane,
)

from .conftest import HANG, Scripted

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


async def test_chord_leaves_the_console_prompt(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app.query_one("#editor", NvimPane).channel > 0)
        prompt = app.console_pane.prompt
        prompt.focus()
        await pilot.press(*"ab")

        await pilot.press("ctrl+g", "1")
        assert isinstance(app.focused, NvimPane)
        assert prompt.value == "ab"


async def test_empty_editor_has_no_intro_screen(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=(200, 80)) as pilot:  # Neovim skips the intro when cramped
        editor = app.query_one("#editor", NvimPane)
        await until(lambda: editor.grid.row_text(1).startswith("~"), what="an empty buffer")
        await pilot.pause(0.3)
        screen = "\n".join(editor.grid.row_text(y) for y in range(editor.grid.height))
        assert "NVIM v" not in screen


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


async def test_tab_completes_at_the_prompt(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")
        await app.kernel.execute("zz_unique_name = 1")
        await until(lambda: "zz_unique_name" in names(app.variables), what="the variable")

        app.console_pane.prompt.focus()
        await pilot.press(*"zz_uni")
        await pilot.press("tab")

        await until(
            lambda: app.console_pane.prompt.value == "zz_unique_name",
            what="the completed name",
        )


async def test_tab_does_not_move_focus(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")
        prompt = app.console_pane.prompt
        prompt.focus()
        await pilot.press(*"x")
        await pilot.press("tab")
        assert app.focused is prompt


async def open_variable(app: PyStudioApp, pilot, name: str) -> None:
    """Put the cursor on a variable row and press enter."""
    await until(lambda: name in names(app.variables), what=f"{name} in the table")
    table = app.variables
    table.focus()
    table.move_cursor(row=table.get_row_index(name))
    await pilot.press("enter")


async def test_enter_on_a_dataframe_opens_the_viewer(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")
        await app.kernel.execute(
            "import pandas as pd\nshown = pd.DataFrame({'a': [3, 1, 2], 'b': [4, 5, 6]})"
        )
        await open_variable(app, pilot, "shown")

        await until(lambda: isinstance(app.screen, FrameViewer), what="the viewer")
        viewer = app.screen
        assert isinstance(viewer, FrameViewer)
        await until(lambda: viewer.table.row_count == 3, what="the rows")
        assert [str(column.label) for column in viewer.table.ordered_columns] == ["", "a", "b"]

        await pilot.press("escape")
        await until(lambda: not isinstance(app.screen, FrameViewer), what="the viewer closed")


async def test_viewer_sorts_through_the_kernel(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")
        await app.kernel.execute("import pandas as pd\nshown = pd.DataFrame({'a': [3, 1, 2]})")
        await open_variable(app, pilot, "shown")
        await until(lambda: isinstance(app.screen, FrameViewer), what="the viewer")
        viewer = app.screen
        assert isinstance(viewer, FrameViewer)
        await until(lambda: viewer.table.row_count == 3, what="the rows")

        def column_a() -> list[str]:
            return [str(viewer.table.get_cell_at((row, 1))) for row in range(3)]

        assert column_a() == ["3", "1", "2"]
        await pilot.press("right")  # off the index column, onto `a`
        await pilot.press("s")
        await until(lambda: column_a() == ["1", "2", "3"], what="an ascending sort")
        await pilot.press("s")
        await until(lambda: column_a() == ["3", "2", "1"], what="a descending sort")


async def test_enter_on_a_scalar_prints_it_in_the_console(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a running kernel")
        await app.kernel.execute("answer = 42")
        await open_variable(app, pilot, "answer")

        await until(lambda: "42" in transcript(app), what="the value in the console")
        assert not isinstance(app.screen, FrameViewer)


async def test_chord_k_switches_the_kernel(tmp_path, monkeypatch) -> None:
    other = KernelChoice(python=Path(sys.executable), label="other")
    monkeypatch.setattr("pystudio.app.candidates", lambda **_: [KernelChoice(), other])
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a started kernel")
        app._execute("before = 1")
        await until(lambda: "before" in names(app.variables), what="a variable")
        first = app.kernel

        await pilot.press("ctrl+g", "k")
        await until(lambda: isinstance(app.screen, KernelPicker), what="the picker")
        await pilot.press("down", "enter")
        await until(lambda: app.kernel is not first and app._kernel_ready, what="the second kernel")

        assert app.status.kernel_name == "other"
        assert app.variables.row_count == 0
        app._execute("import sys; sys.executable")
        await until(lambda: sys.executable in transcript(app), what="the new interpreter")
        assert first._km is None


async def test_picker_closes_without_switching(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pystudio.app.candidates", lambda **_: [KernelChoice()])
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a started kernel")
        first = app.kernel
        await pilot.press("ctrl+g", "k")
        await until(lambda: isinstance(app.screen, KernelPicker), what="the picker")
        await pilot.press("escape")
        await until(lambda: not isinstance(app.screen, KernelPicker), what="the picker to close")
        assert app.kernel is first


async def test_chord_a_shows_the_assistant_and_2_the_console(tmp_path) -> None:
    app = app_with(tmp_path, assistant=Scripted())
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app.editor.channel > 0)
        assert not app.assistant_pane.display

        await pilot.press("ctrl+g", "a")
        assert app.assistant_pane.display and not app.console_pane.display
        assert app.focused is app.assistant_pane.prompt

        await pilot.press("ctrl+g", "2")
        assert app.console_pane.display and not app.assistant_pane.display
        assert app.focused is not None and app.focused in app.console_pane.query("*")


async def ask(app: PyStudioApp, pilot, text: str) -> None:
    await pilot.press("ctrl+g", "a")
    app.assistant_pane.prompt.value = text
    await pilot.press("enter")


async def buffer(app: PyStudioApp) -> list[str]:
    return (await app.editor.snapshot())[1]


async def test_the_assistant_writes_cells_that_one_undo_removes(tmp_path) -> None:
    cells = [
        {"title": "Load", "code": "df = 1"},
        {"title": "Look", "code": "df"},
    ]
    provider = Scripted(
        [ToolCall("t1", "insert_cells", {"cells": cells}), TurnEnd("tools")],
        [TextDelta("Added two cells."), TurnEnd("done")],
    )
    app = app_with(tmp_path, assistant=provider)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app.editor.channel > 0)
        await ask(app, pilot, "load it")
        await until(lambda: app._asking is None and not provider.turns, what="the turn to end")

        assert await buffer(app) == ["# %% Load", "df = 1", "", "# %% Look", "df"]
        chat = app.assistant_pane.transcript
        assert "you  load it" in chat
        assert "inserted 2 cells" in chat
        assert "Added two cells." in chat
        assert app.status.note == ""

        await pilot.press("ctrl+g", "1")
        await pilot.press("u")
        await until_async(lambda: buffer(app), [""], what="the undo")


async def until_async(read, expected, *, what: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await read() == expected:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{what} never happened within {timeout}s")


async def test_the_assistant_inspects_the_real_kernel(tmp_path) -> None:
    provider = Scripted(
        [ToolCall("t1", "inspect", {"expression": "answer * 2"}), TurnEnd("tools")],
        [TurnEnd("done")],
    )
    app = app_with(tmp_path, assistant=provider)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app._kernel_ready, what="a started kernel")
        app._execute("answer = 21")
        await until(lambda: "answer" in names(app.variables), what="the variable")
        await ask(app, pilot, "what is it")
        await until(lambda: app._asking is None and not provider.turns, what="the turn to end")

        assert provider.sent[1][1][0].text == "42"
        assert "answer * 2" not in transcript(app), "inspection stays out of the console"


async def test_escape_cancels_a_reply(tmp_path) -> None:
    provider = Scripted([TextDelta("Thinking about"), HANG])
    app = app_with(tmp_path, assistant=provider)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app.editor.channel > 0)
        await ask(app, pilot, "something slow")
        await until(lambda: "Thinking about" in app.assistant_pane.transcript, what="a reply")
        assert app.status.note == "assistant…"

        await pilot.press("escape")
        await until(lambda: app._asking is None, what="the cancel")
        assert "cancelled" in app.assistant_pane.transcript


async def test_no_credentials_is_a_note_in_the_chat(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PYSTUDIO_ASSISTANT", "nope")
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await until(lambda: app.editor.channel > 0)
        await ask(app, pilot, "hello")
        await until(lambda: app._asking is None, what="the turn to end")
        assert "unknown assistant provider" in app.assistant_pane.transcript


async def test_sending_the_file_runs_cells_and_stops_at_a_failure(tmp_path) -> None:
    app = app_with(tmp_path)
    async with app.run_test(size=SIZE):
        await until(lambda: app._kernel_ready, what="a started kernel")
        script = ["# %%", "first = 1", "# %%", "this is not python", "# %%", "third = 3"]
        await app.editor.set_lines(0, -1, script)
        await app.editor.rpc.request("nvim_exec_lua", "pystudio.send_file()", [])

        await until(lambda: "stopped at the cell on line 3" in transcript(app), what="the stop")
        assert "1 cell after it not run" in transcript(app)
        await until(lambda: "first" in names(app.variables), what="the first cell's variable")
        assert "third" not in names(app.variables)
        assert app._running_cells is None
