"""Transport and redraw against a real Neovim process."""

from __future__ import annotations

import shutil

import pytest

from pystudio.nvim import NvimError

from .conftest import NvimHarness

pytestmark = pytest.mark.skipif(shutil.which("nvim") is None, reason="nvim is not installed")


async def test_attach_reports_a_channel(nvim: NvimHarness) -> None:
    assert nvim.channel > 0


async def test_typing_reaches_the_grid(nvim: NvimHarness) -> None:
    nvim.rpc.notify("nvim_input", "ihello")
    await nvim.wait_until(
        lambda: nvim.grid.row_text(0).startswith("hello"),
        what="typed text on screen",
    )


async def test_mode_change_is_reported(nvim: NvimHarness) -> None:
    nvim.rpc.notify("nvim_input", "i")
    await nvim.wait_until(lambda: nvim.grid.mode == "insert", what="insert mode")
    nvim.rpc.notify("nvim_input", "<Esc>")
    await nvim.wait_until(lambda: nvim.grid.mode == "normal", what="normal mode")


async def test_colors_and_styles_arrive(nvim: NvimHarness) -> None:
    # Any Neovim sends default colors and at least one highlight on attach.
    assert nvim.grid.style_for(0).bgcolor is not None


async def test_resize_is_honoured(nvim: NvimHarness) -> None:
    await nvim.rpc.request("nvim_ui_try_resize", 100, 30)
    await nvim.wait_until(
        lambda: (nvim.grid.width, nvim.grid.height) == (100, 30),
        what="resized grid",
    )


async def test_request_errors_become_exceptions(nvim: NvimHarness) -> None:
    with pytest.raises(NvimError):
        await nvim.rpc.request("nvim_no_such_method")


async def test_buffer_api_round_trip(nvim: NvimHarness) -> None:
    await nvim.rpc.request("nvim_buf_set_lines", 0, 0, -1, False, ["x = 1", "y = 2"])
    lines = await nvim.rpc.request("nvim_buf_get_lines", 0, 0, -1, False)
    assert lines == ["x = 1", "y = 2"]
