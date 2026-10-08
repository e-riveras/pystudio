"""Buffers follow their files when something else writes them."""

from __future__ import annotations

import os
import shutil

import pytest

from .conftest import NvimHarness

pytestmark = pytest.mark.skipif(shutil.which("nvim") is None, reason="nvim is not installed")


async def lines(nvim: NvimHarness) -> list[str]:
    return await nvim.rpc.request("nvim_buf_get_lines", 0, 0, -1, False)


async def open_file(nvim: NvimHarness, path) -> None:
    await nvim.install_send_lua()
    await nvim.rpc.request("nvim_command", f"edit {path}")


async def wait_for_lines(nvim: NvimHarness, expected: list[str]) -> None:
    current: list[str] = []

    async def check() -> bool:
        nonlocal current
        current = await lines(nvim)
        return current == expected

    import asyncio
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if await check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"buffer is {current}, expected {expected}")


async def test_an_outside_write_reaches_a_clean_buffer(nvim: NvimHarness, tmp_path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n")
    await open_file(nvim, path)

    path.write_text("x = 1\ny = 2\n")
    await wait_for_lines(nvim, ["x = 1", "y = 2"])

    await nvim.rpc.request("nvim_command", "normal! u")
    assert await lines(nvim) == ["x = 1"], "a reload is one undo step"


async def test_a_rename_over_the_file_is_followed(nvim: NvimHarness, tmp_path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n")
    await open_file(nvim, path)

    for version in ("x = 2", "x = 3"):
        temporary = tmp_path / "a.py.tmp"
        temporary.write_text(version + "\n")
        os.replace(temporary, path)
        await wait_for_lines(nvim, [version])


async def test_unsaved_changes_are_kept(nvim: NvimHarness, tmp_path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n")
    await open_file(nvim, path)
    await nvim.rpc.request("nvim_buf_set_lines", 0, 0, -1, False, ["mine = 1"])

    path.write_text("theirs = 1\n")
    import asyncio

    await asyncio.sleep(0.5)
    assert await lines(nvim) == ["mine = 1"]
    mode = await nvim.rpc.request("nvim_get_mode")
    assert not mode["blocking"], "no prompt may block the editor"
