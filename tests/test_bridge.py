"""The agent's kernel tools, end to end: MCP client, bridge process, socket, workspace."""

from __future__ import annotations

import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from pystudio.assistant.bridge import Bridge

from .test_assistant import Lists


async def test_kernel_tools_reach_the_workspace_over_mcp() -> None:
    bridge = Bridge(Lists())
    path = await bridge.start()
    try:
        assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "pystudio.mcp_bridge", "--socket", str(path)]
        )
        async with Client(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == {"list_variables", "inspect", "read_console"}

            listed = await client.call_tool("list_variables", {})
            assert "df\tDataFrame" in listed.content[0].text

            inspected = await client.call_tool("inspect", {"expression": "df.shape"})
            assert inspected.content[0].text == "42"

            failed = await client.call_tool("inspect", {"expression": "boom"})
            assert "NameError" in failed.content[0].text
    finally:
        await bridge.stop()
    assert not path.parent.exists()


async def test_only_kernel_tools_are_served() -> None:
    bridge = Bridge(Lists(["a = 1"]))
    answer = await bridge.answer(b'{"name": "replace_lines", "input": {}}')
    assert answer["is_error"]
    assert (await bridge.answer(b"not json"))["is_error"]
