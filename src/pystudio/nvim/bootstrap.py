"""Lua shipped with pystudio and installed into the embedded Neovim."""

from __future__ import annotations

from importlib.resources import files

SEND_LUA = "send.lua"


def load_lua(name: str = SEND_LUA) -> str:
    """Read a packaged Lua file."""
    return files("pystudio").joinpath("lua", name).read_text(encoding="utf-8")
