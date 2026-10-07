"""The workspace the tools act on, over the running app."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pystudio.introspect import Variable

if TYPE_CHECKING:
    from pystudio.app import PyStudioApp


class KernelNotReady(Exception):
    def __str__(self) -> str:
        return "the kernel is not running yet"


class AppWorkspace:
    """Reads through to the app on every call, since the kernel can be switched."""

    def __init__(self, app: PyStudioApp) -> None:
        self.app = app

    @property
    def cwd(self) -> Path:
        return self.app.cwd

    async def buffer(self) -> tuple[str, list[str], int]:
        return await self.app.editor.snapshot()

    async def cell_end(self) -> int:
        return await self.app.editor.cell_end()

    async def set_lines(self, start: int, end: int, lines: list[str]) -> None:
        await self.app.editor.set_lines(start, end, lines)

    async def move_cursor(self, line: int) -> None:
        await self.app.editor.move_cursor(line)

    async def variables(self) -> list[Variable]:
        if not self.app.kernel_ready:
            raise KernelNotReady
        return await self.app.kernel.variables()

    async def evaluate(self, expression: str) -> tuple[bool, str]:
        if not self.app.kernel_ready:
            raise KernelNotReady
        return await self.app.kernel.evaluate(expression)

    def console_tail(self, lines: int) -> str:
        return self.app.console_pane.tail(lines)
