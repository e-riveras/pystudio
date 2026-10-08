"""Coding agents that can run in the agent pane, and how to start each one.

Each agent is its own CLI, run as is in a terminal, so it keeps the user's
subscription login and its own interface. pystudio adds two things on the
command line: its MCP server, for the kernel, and a few words of context.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AGENT = "claude"
AGENT_VARIABLE = "PYSTUDIO_AGENT"

PROMPT = """\
You are running inside pystudio, a terminal IDE for Python data science. The user's \
editor is Neovim, next to you on screen, and it reloads a file the moment you change \
it, so your edits appear live in their buffer and they can undo each one with `u`. \
Scripts are made of cells, each starting with a `# %%` marker; the user sends cells to \
a Jupyter kernel themselves. When you add analysis code, add it as cells. The \
`pystudio` MCP server shows that live kernel: list_variables, inspect for the value \
of an expression, and read_console for output and tracebacks. Use it to look at the \
real data before writing code for it. It never runs the user's cells.\
"""


def bridge_command(socket: Path) -> dict[str, object]:
    """The MCP server entry: pystudio's own Python, so the ``mcp`` package is there."""
    return {
        "command": sys.executable,
        "args": ["-m", "pystudio.mcp_bridge", "--socket", str(socket)],
    }


@dataclass(frozen=True)
class Agent:
    name: str
    command: Callable[[Path], list[str]]
    """The command line, given the bridge socket."""


def claude(socket: Path) -> list[str]:
    config = {"mcpServers": {"pystudio": bridge_command(socket)}}
    return ["claude", "--mcp-config", json.dumps(config), "--append-system-prompt", PROMPT]


AGENTS = {"claude": Agent("claude", claude)}


def choose(name: str | None = None) -> Agent:
    """The named agent, or the one in ``$PYSTUDIO_AGENT``, or Claude Code."""
    name = name or os.environ.get(AGENT_VARIABLE) or DEFAULT_AGENT
    if name not in AGENTS:
        known = ", ".join(sorted(AGENTS))
        raise ValueError(f"unknown agent {name!r}; known: {known}")
    return AGENTS[name]
