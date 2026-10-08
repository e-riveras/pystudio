"""Lua shipped with pystudio and installed into the embedded Neovim."""

from __future__ import annotations

from importlib.resources import files

LUA_FILES = ("send.lua", "cells.lua", "reload.lua")
"""Installed in order: cells.lua uses what send.lua puts in ``_G.pystudio``."""


def load_lua(name: str = LUA_FILES[0]) -> str:
    """Read a packaged Lua file."""
    return files("pystudio").joinpath("lua", name).read_text(encoding="utf-8")


def load_all() -> list[tuple[str, str]]:
    """Every packaged Lua file, in installation order."""
    return [(name, load_lua(name)) for name in LUA_FILES]
