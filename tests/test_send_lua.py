"""The editor-to-kernel path, exercised inside a real Neovim."""

from __future__ import annotations

import shutil

import pytest

from .conftest import NvimHarness

pytestmark = pytest.mark.skipif(shutil.which("nvim") is None, reason="nvim is not installed")

SCRIPT = [
    "# %%",
    "x = 1",
    "y = 2",
    "# %%",
    "z = 3",
]


async def fill(nvim: NvimHarness, lines: list[str], *, row: int = 1) -> None:
    await nvim.install_send_lua()
    await nvim.rpc.request("nvim_buf_set_lines", 0, 0, -1, False, lines)
    await nvim.rpc.request("nvim_win_set_cursor", 0, [row, 0])
    nvim.notifications.clear()


async def test_send_line_notifies_and_advances(nvim: NvimHarness) -> None:
    await fill(nvim, ["x = 1", "y = 2"])
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_line()", [])

    assert nvim.sent() == [("pystudio_send", [["x = 1"]])]
    assert await nvim.rpc.request("nvim_win_get_cursor", 0) == [2, 0]


async def test_send_line_stops_at_the_last_line(nvim: NvimHarness) -> None:
    await fill(nvim, ["only = 1"])
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_line()", [])
    assert await nvim.rpc.request("nvim_win_get_cursor", 0) == [1, 0]


async def test_localleader_mapping_is_installed(nvim: NvimHarness) -> None:
    await fill(nvim, ["x = 1", "y = 2"])
    nvim.rpc.notify("nvim_input", "\\l")
    await nvim.wait_until(lambda: bool(nvim.sent()), what="a send from the keymap")
    assert nvim.sent()[0] == ("pystudio_send", [["x = 1"]])


async def test_visual_selection_is_sent_whole(nvim: NvimHarness) -> None:
    await fill(nvim, ["a = 1", "b = 2", "c = 3"])
    nvim.rpc.notify("nvim_input", "Vj")
    await nvim.wait_until(lambda: nvim.grid.mode.startswith("visual"), what="visual mode")

    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_line()", [])
    assert nvim.sent() == [("pystudio_send", [["a = 1", "b = 2"]])]
    # Visual mode is left synchronously, so the next send is a fresh chunk.
    assert (await nvim.rpc.request("nvim_get_mode"))["mode"] == "n"


async def test_send_cell_uses_the_markers(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=2)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_cell()", [])
    assert nvim.sent() == [("pystudio_send", [["x = 1", "y = 2"]])]


async def test_send_cell_in_the_last_cell(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=5)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_cell()", [])
    assert nvim.sent() == [("pystudio_send", [["z = 3"]])]


async def test_send_file_sends_every_line(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_file()", [])
    assert nvim.sent() == [("pystudio_send", [SCRIPT])]


async def test_control_commands(nvim: NvimHarness) -> None:
    await fill(nvim, ["x = 1"])
    await nvim.rpc.request("nvim_command", "PyStudioInterrupt")
    await nvim.rpc.request("nvim_command", "PyStudioRestart")
    assert nvim.sent() == [
        ("pystudio_control", ["interrupt"]),
        ("pystudio_control", ["restart"]),
    ]


async def test_buffer_changes_are_announced(nvim: NvimHarness, tmp_path) -> None:
    await nvim.install_send_lua()
    nvim.notifications.clear()
    target = tmp_path / "analysis.py"
    target.write_text("x = 1\n")
    await nvim.rpc.request("nvim_command", f"edit {target}")
    await nvim.wait_until(
        lambda: any(method == "pystudio_buffer" for method, _ in nvim.sent()),
        what="a buffer announcement",
    )
    method, params = next(item for item in nvim.sent() if item[0] == "pystudio_buffer")
    assert params[0].endswith("analysis.py")
