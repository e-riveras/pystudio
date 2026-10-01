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


async def cursor(nvim: NvimHarness) -> list[int]:
    return await nvim.rpc.request("nvim_win_get_cursor", 0)


async def test_send_cell_advances_to_the_next_cell(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=2)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_cell()", [])
    assert nvim.sent() == [("pystudio_send", [["x = 1", "y = 2"]])]
    # Line 4 is the next `# %%`, so the cursor lands on line 5, its first line.
    assert await cursor(nvim) == [5, 0]


async def test_send_cell_in_the_last_cell_stays_put(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=5)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_cell()", [])
    assert nvim.sent() == [("pystudio_send", [["z = 3"]])]
    assert await cursor(nvim) == [5, 0]


async def test_upward_selection_advances_past_its_bottom(nvim: NvimHarness) -> None:
    await fill(nvim, ["a = 1", "b = 2", "c = 3", "d = 4"], row=3)
    nvim.rpc.notify("nvim_input", "Vk")  # select lines 3 and 2, cursor ends on 2
    await nvim.wait_until(lambda: nvim.grid.mode.startswith("visual"), what="visual mode")

    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_line()", [])
    assert nvim.sent() == [("pystudio_send", [["b = 2", "c = 3"]])]
    assert await cursor(nvim) == [4, 0]


async def test_send_above(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=5)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_above()", [])
    assert nvim.sent() == [("pystudio_send", [SCRIPT[:3]])]


async def test_send_above_sends_nothing_in_the_first_cell(nvim: NvimHarness) -> None:
    await fill(nvim, ["x = 1", "y = 2"], row=2)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_above()", [])
    assert nvim.sent() == []


async def test_send_to_end(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=4)
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_to_end()", [])
    assert nvim.sent() == [("pystudio_send", [SCRIPT[3:]])]


async def test_send_last_repeats(nvim: NvimHarness) -> None:
    await fill(nvim, ["x = 1", "y = 2"])
    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_line()", [])
    nvim.notifications.clear()

    await nvim.rpc.request("nvim_exec_lua", "pystudio.send_last()", [])
    assert nvim.sent() == [("pystudio_send", [["x = 1"]])]


async def test_keys_are_offered_under_a_separate_leader(nvim: NvimHarness) -> None:
    await nvim.rpc.request("nvim_exec_lua", "vim.g.mapleader = ' '", [])
    await fill(nvim, ["x = 1", "y = 2"])

    keys = await nvim.rpc.request("nvim_get_var", "pystudio_keys")
    assert "\\l" in keys
    assert " l" in keys

    nvim.rpc.notify("nvim_input", " l")
    await nvim.wait_until(lambda: bool(nvim.sent()), what="a send from <leader>l")
    assert nvim.sent()[0] == ("pystudio_send", [["x = 1"]])


async def test_an_existing_mapping_is_not_clobbered(nvim: NvimHarness) -> None:
    await nvim.rpc.request("nvim_exec_lua", "vim.g.mapleader = ' '", [])
    await nvim.rpc.request(
        "nvim_exec_lua",
        "vim.keymap.set('n', '<leader>l', function() vim.g.mine = true end)",
        [],
    )
    await fill(nvim, ["x = 1"])

    keys = await nvim.rpc.request("nvim_get_var", "pystudio_keys")
    assert "\\l" in keys
    assert " l" not in keys

    nvim.rpc.notify("nvim_input", " l")
    await nvim.wait_until(
        lambda: True,  # give the input a tick to be processed
        what="the input to settle",
    )
    assert await nvim.rpc.request("nvim_eval", "get(g:, 'mine', v:false)") is True
    assert nvim.sent() == []


async def extmark_count(nvim: NvimHarness, namespace: str) -> int:
    marks = await nvim.rpc.request(
        "nvim_exec_lua",
        f"return vim.api.nvim_buf_get_extmarks(0, pystudio_cells.{namespace}, 0, -1, {{}})",
        [],
    )
    return len(marks)


async def test_cell_rules_are_drawn_above_each_marker(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=2)
    await nvim.rpc.request("nvim_exec_lua", "vim.bo.filetype = 'python'", [])
    await nvim.rpc.request("nvim_exec_lua", "pystudio_cells.redraw()", [])

    # Two markers, but the one on line 1 has nothing above it to separate.
    assert await extmark_count(nvim, "rules_ns") == 1


async def test_the_current_cell_is_washed_and_follows_the_cursor(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=2)
    await nvim.rpc.request("nvim_exec_lua", "vim.bo.filetype = 'python'", [])
    await nvim.rpc.request("nvim_exec_lua", "pystudio_cells.redraw()", [])
    assert await extmark_count(nvim, "current_ns") == 2  # lines 2 and 3

    await nvim.rpc.request("nvim_win_set_cursor", 0, [5, 0])
    await nvim.rpc.request("nvim_exec_lua", "pystudio_cells.redraw()", [])
    assert await extmark_count(nvim, "current_ns") == 1  # line 5 alone


async def test_decoration_stays_out_of_other_filetypes(nvim: NvimHarness) -> None:
    await fill(nvim, SCRIPT, row=2)
    await nvim.rpc.request("nvim_exec_lua", "vim.bo.filetype = 'markdown'", [])
    await nvim.rpc.request("nvim_exec_lua", "pystudio_cells.redraw()", [])
    assert await extmark_count(nvim, "rules_ns") == 0
    assert await extmark_count(nvim, "current_ns") == 0


async def test_a_mapping_prefix_is_not_shadowed(nvim: NvimHarness) -> None:
    """`<leader>f` would make the user wait out timeoutlen for `<leader>ff`."""
    await nvim.rpc.request("nvim_exec_lua", "vim.g.mapleader = ' '", [])
    await nvim.rpc.request(
        "nvim_exec_lua",
        "vim.keymap.set('n', '<leader>ff', function() vim.g.theirs = true end)",
        [],
    )
    await fill(nvim, ["x = 1"])

    keys = await nvim.rpc.request("nvim_get_var", "pystudio_keys")
    skipped = await nvim.rpc.request("nvim_get_var", "pystudio_keys_skipped")
    assert " f" not in keys
    assert " f" in skipped
    # The other keys are unaffected.
    assert " l" in keys
    assert "\\f" in keys
