"""An MCP server that lets a coding agent look at pystudio's kernel.

The agent starts this as ``python -m pystudio.mcp_bridge --socket PATH``. Each
tool forwards to the running pystudio over that Unix socket; nothing here
touches the kernel or the UI directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pystudio.assistant.tools import CONSOLE_LINES, SPECS

INSTRUCTIONS = (
    "Tools for the live Python kernel in the user's pystudio session: the variables "
    "it holds, the value of an expression, and what the console printed. Use them to "
    "look at real data before writing code for it. They never run the user's cells."
)

DESCRIPTIONS = {spec.name: spec.description for spec in SPECS}


class Connection:
    """One socket to pystudio, opened on first use and shared by every call."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._streams: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
        self._lock = asyncio.Lock()

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        async with self._lock:
            try:
                if self._streams is None:
                    self._streams = await asyncio.open_unix_connection(self.path)
                reader, writer = self._streams
                writer.write(json.dumps({"name": name, "input": arguments}).encode() + b"\n")
                await writer.drain()
                line = await reader.readline()
            except OSError as error:
                self._streams = None
                raise ToolError(f"pystudio is not reachable: {error}") from error
            if not line:
                self._streams = None
                raise ToolError("pystudio closed the connection; it may have exited")
        answer = json.loads(line)
        if answer.get("is_error"):
            raise ToolError(str(answer.get("text", "")))
        return str(answer.get("text", ""))


def build(path: str) -> MCPServer:
    connection = Connection(path)
    server = MCPServer("pystudio", instructions=INSTRUCTIONS)

    async def list_variables() -> str:
        return await connection.call("list_variables", {})

    async def inspect(expression: str) -> str:
        return await connection.call("inspect", {"expression": expression})

    async def read_console(lines: int = CONSOLE_LINES) -> str:
        return await connection.call("read_console", {"lines": lines})

    for tool in (list_variables, inspect, read_console):
        server.add_tool(tool, name=tool.__name__, description=DESCRIPTIONS[tool.__name__])
    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pystudio.mcp_bridge")
    parser.add_argument("--socket", required=True, help="pystudio's bridge socket")
    args = parser.parse_args(argv)
    build(args.socket).run("stdio")


if __name__ == "__main__":
    main()
