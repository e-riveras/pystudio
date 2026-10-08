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
from importlib.resources import files
from pathlib import Path

DEFAULT_AGENT = "claude"
AGENT_VARIABLE = "PYSTUDIO_AGENT"
"""Set to an agent's name to turn the agent pane on without the command line flag."""

PROFILE_VARIABLE = "PYSTUDIO_AGENT_PROFILE"
"""Set to ``off`` to start the agent without pystudio's data science skill."""

PLUGIN = "pystudio"
SKILL = "data-science"

PROMPT = f"""\
You are running inside pystudio, a terminal IDE for Python data science. The user's \
editor is Neovim, next to you on screen, and it reloads a file the moment you change \
it, so your edits appear live in their buffer and they can undo each one with `u`. \
Scripts are made of cells, each starting with a `# %%` marker; the user sends cells to \
a Jupyter kernel themselves. When you add analysis code, add it as cells. The \
`pystudio` MCP server shows that live kernel: list_variables, inspect for the value \
of an expression, and read_console for output and tracebacks. Use it to look at the \
real data before writing code for it. It never runs the user's cells. \
The `{PLUGIN}:{SKILL}` skill holds the conventions for analysis work here: read it \
before you write or change analysis code.\
"""


def profile_enabled() -> bool:
    return os.environ.get(PROFILE_VARIABLE, "").strip().lower() not in ("off", "0", "no", "false")


def write_profile(directory: Path) -> Path:
    """Lay pystudio's data science skill out as a Claude Code plugin under ``directory``.

    The skill ships as one Markdown file; the plugin around it is written at
    start, next to the bridge socket, and goes away with it.
    """
    plugin = directory / "plugin"
    manifest = plugin / ".claude-plugin" / "plugin.json"
    skill = plugin / "skills" / SKILL / "SKILL.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    skill.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "name": PLUGIN,
                "description": "Working conventions for data science inside pystudio.",
                "version": "1.0.0",
            },
            indent=2,
        )
    )
    source = files("pystudio").joinpath("agent_profile", "SKILL.md")
    skill.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return plugin


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
    without_env: tuple[str, ...] = ()
    """Variables kept from the agent, so it uses its own login."""


def claude(socket: Path) -> list[str]:
    config = {"mcpServers": {"pystudio": bridge_command(socket)}}
    argv = ["claude", "--mcp-config", json.dumps(config), "--append-system-prompt", PROMPT]
    if profile_enabled():
        argv += ["--plugin-dir", str(write_profile(socket.parent))]
    return argv


# An API key in the environment, such as the one the --assistant feature uses,
# would take precedence over the Claude Code login and bill the API instead of
# the subscription, or fail outright if the key is not valid for it.
AGENTS = {
    "claude": Agent("claude", claude, without_env=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
}


def choose(name: str) -> Agent:
    """The named agent. Raises ValueError for one that is not known."""
    if name not in AGENTS:
        known = ", ".join(sorted(AGENTS))
        raise ValueError(f"unknown agent {name!r}; known: {known}")
    return AGENTS[name]
