"""The app's end of the agent's kernel tools: a private Unix socket.

The coding agent starts :mod:`pystudio.mcp_bridge` as its MCP server, and that
process forwards each tool call here, one JSON line per request. Calls run
through the same tools as the API assistant, limited to the read-only ones.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from pathlib import Path

from pystudio.assistant import tools
from pystudio.assistant.provider import ToolCall
from pystudio.kernel import socket_dir

ALLOWED = ("list_variables", "inspect", "read_console")
"""Kernel tools only. The agent edits files itself, and runs no cells."""


class Bridge:
    """Serves tool calls from the agent's MCP server against a workspace."""

    def __init__(self, workspace: tools.Workspace) -> None:
        self.workspace = workspace
        self._directory: Path | None = None
        self._server: asyncio.Server | None = None

    @property
    def path(self) -> Path:
        if self._directory is None:
            raise RuntimeError("the bridge is not started")
        return self._directory / "bridge"

    async def start(self) -> Path:
        if self._server is None:
            self._directory = socket_dir()
            self._server = await asyncio.start_unix_server(self._serve, path=str(self.path))
        return self.path

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 1.0)
            self._server = None
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)
            self._directory = None

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await reader.readline():
                answer = await self.answer(line)
                writer.write(json.dumps(answer).encode() + b"\n")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    async def answer(self, line: bytes) -> dict[str, object]:
        try:
            request = json.loads(line)
            name, arguments = request["name"], request.get("input") or {}
            if not isinstance(arguments, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            return {"text": "malformed request", "is_error": True}
        if name not in ALLOWED:
            return {"text": f"{name} is not available to the agent", "is_error": True}
        result, _ = await tools.run(self.workspace, ToolCall("bridge", name, arguments))
        return {"text": result.text, "is_error": result.is_error}
