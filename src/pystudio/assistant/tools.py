"""What the assistant can do: read the editor, write cells, look at the kernel.

Each tool acts on a :class:`Workspace`, which the app implements over the real
Neovim and kernel and the tests implement over lists. Tool input comes from a
model and is not validated by the API, so every tool checks its own before it
touches anything, and a bad call becomes an error result rather than an
exception.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from pystudio.assistant.provider import ToolCall, ToolResult, ToolSpec
from pystudio.introspect import Variable

PEEK_LINES = 20
PEEK_MAX_LINES = 200
PEEK_MAX_BYTES = 20_000
CONSOLE_LINES = 40
CONSOLE_MAX_LINES = 400
REPR_LIMIT = 4000
"""Longest repr handed back from ``inspect``; a wide frame is cut, not refused."""


class Workspace(Protocol):
    """The editor, the kernel and the console, as the tools need them."""

    cwd: Path

    async def buffer(self) -> tuple[str, list[str], int]:
        """File name, lines, and the cursor's line counted from 1."""
        ...

    async def cell_end(self) -> int:
        """The last line, from 1, of the cell holding the cursor."""
        ...

    async def set_lines(self, start: int, end: int, lines: list[str]) -> None:
        """Replace lines ``start`` to ``end``, from 0 and end-exclusive."""
        ...

    async def move_cursor(self, line: int) -> None: ...

    async def variables(self) -> list[Variable]: ...

    async def evaluate(self, expression: str) -> tuple[bool, str]: ...

    def console_tail(self, lines: int) -> str: ...


class BadInput(Exception):
    """The model called a tool with input the tool cannot use."""


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


SPECS = [
    ToolSpec(
        "read_buffer",
        "Read the editor buffer: its file name, the cursor's line, and every line with its "
        "number. Call this before writing, so new code fits what is already there, and before "
        "replace_lines, whose line numbers come from here.",
        _object({}, []),
    ),
    ToolSpec(
        "insert_cells",
        "Write new cells into the editor. Each cell becomes a `# %% title` marker followed by "
        "its code. The user runs the cells themselves; nothing is executed. One call is one "
        "undo step, so put everything for one request in a single call.",
        _object(
            {
                "cells": {
                    "type": "array",
                    "items": _object(
                        {
                            "title": {"type": "string", "description": "A few words, one line."},
                            "code": {"type": "string", "description": "Python, no marker line."},
                        },
                        ["title", "code"],
                    ),
                },
                "where": {
                    "type": "string",
                    "enum": ["after_cursor_cell", "end"],
                    "description": "after_cursor_cell (the default) or the end of the buffer.",
                },
            },
            ["cells"],
        ),
    ),
    ToolSpec(
        "replace_lines",
        "Replace lines start to end, inclusive and counted from 1, with new code. Use it to "
        "change code that already exists, with line numbers from a fresh read_buffer.",
        _object(
            {
                "start": {"type": "integer"},
                "end": {"type": "integer"},
                "code": {"type": "string", "description": "Empty to delete the lines."},
            },
            ["start", "end", "code"],
        ),
    ),
    ToolSpec(
        "list_variables",
        "List the variables in the running kernel: name, type, shape and a short preview.",
        _object({}, []),
    ),
    ToolSpec(
        "inspect",
        "Evaluate one Python expression in the user's kernel and return its repr, to look at "
        "data before writing code for it: `df.dtypes`, `df.head()`, `df.isna().sum()`, "
        "`pd.read_csv('x.csv', nrows=5)`. It is an expression, not a statement. It runs in "
        "the user's live session and is shown to them, so it must only look: never assign, "
        "mutate, write files, install packages or start long computations.",
        _object({"expression": {"type": "string"}}, ["expression"]),
    ),
    ToolSpec(
        "peek_file",
        "Read the first lines of a text file, such as a CSV, without the kernel. Relative "
        f"paths start at the editor file's directory. At most {PEEK_MAX_LINES} lines.",
        _object(
            {
                "path": {"type": "string"},
                "lines": {"type": "integer", "description": f"Default {PEEK_LINES}."},
            },
            ["path"],
        ),
    ),
    ToolSpec(
        "read_console",
        "Read the end of the console: what the user's cells printed, and their tracebacks.",
        _object({"lines": {"type": "integer", "description": f"Default {CONSOLE_LINES}."}}, []),
    ),
]


async def run(workspace: Workspace, call: ToolCall) -> tuple[ToolResult, str]:
    """Run one tool call. Returns its result and a line describing it for the chat."""
    tool = TOOLS.get(call.name)
    try:
        if tool is None:
            raise BadInput(f"there is no tool named {call.name}")
        text, note = await tool(workspace, call.input)
    except BadInput as error:
        return ToolResult(call.id, f"invalid input: {error}", is_error=True), (
            f"{call.name} failed: {error}"
        )
    except TimeoutError:
        message = "the kernel is busy and did not answer in time"
        return ToolResult(call.id, message, is_error=True), f"{call.name}: {message}"
    except Exception as error:  # noqa: BLE001 - the model gets to see and react to it
        return ToolResult(call.id, f"{type(error).__name__}: {error}", is_error=True), (
            f"{call.name} failed: {error}"
        )
    return ToolResult(call.id, text), note


# ---------------------------------------------------------------------- validation


def _string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise BadInput(f"{key} must be a string")
    return value


def _integer(args: dict[str, Any], key: str, default: int | None = None) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadInput(f"{key} must be an integer")
    return value


# --------------------------------------------------------------------------- tools


async def _read_buffer(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    name, lines, cursor = await workspace.buffer()
    width = len(str(len(lines)))
    body = "\n".join(f"{number:>{width}}  {line}" for number, line in enumerate(lines, 1))
    header = f"file: {name or '(no name)'}\ncursor: line {cursor}\nlines: {len(lines)}\n\n"
    return header + body, f"read the buffer, {len(lines)} lines"


def cell_lines(cells: list[tuple[str, str]]) -> list[str]:
    """Cells as buffer lines: a marker, the code, and a blank line between cells."""
    lines: list[str] = []
    for title, code in cells:
        if lines:
            lines.append("")
        lines.append(f"# %% {title}".rstrip())
        lines.extend(code.strip("\n").splitlines())
    return lines


async def _insert_cells(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    raw = args.get("cells")
    if not isinstance(raw, list) or not raw:
        raise BadInput("cells must be a non-empty list")
    cells = []
    for cell in raw:
        if not isinstance(cell, dict):
            raise BadInput("each cell must be an object with title and code")
        title = " ".join(_string(cell, "title").split())
        cells.append((title, _string(cell, "code")))
    where = args.get("where", "after_cursor_cell")
    if where not in ("after_cursor_cell", "end"):
        raise BadInput("where must be after_cursor_cell or end")

    _, lines, _ = await workspace.buffer()
    new = cell_lines(cells)
    if not any(line.strip() for line in lines):
        # An empty buffer is replaced, or the cells would start under a blank line.
        await workspace.set_lines(0, len(lines), new)
        first = 1
    else:
        after = len(lines) if where == "end" else await workspace.cell_end()
        after = max(0, min(after, len(lines)))
        if after and lines[after - 1].strip():
            new.insert(0, "")
        first = after + 1 + (1 if new[0] == "" else 0)
        if after < len(lines) and lines[after].strip():
            new.append("")
        await workspace.set_lines(after, after, new)
    await workspace.move_cursor(first)
    last = first + len(cell_lines(cells)) - 1
    count = f"{len(cells)} cell{'s' if len(cells) != 1 else ''}"
    return (
        f"inserted {count} at lines {first}-{last}; the cursor is on the first",
        f"inserted {count}, lines {first}–{last}",
    )


async def _replace_lines(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    start, end, code = _integer(args, "start"), _integer(args, "end"), _string(args, "code")
    _, lines, _ = await workspace.buffer()
    if not 1 <= start <= end <= len(lines):
        raise BadInput(f"lines {start}-{end} are outside the buffer, which has {len(lines)}")
    new = code.strip("\n").splitlines() if code.strip() else []
    await workspace.set_lines(start - 1, end, new)
    return (
        f"replaced lines {start}-{end} with {len(new)} lines; line numbers after {start} moved",
        f"replaced lines {start}–{end}",
    )


async def _list_variables(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    variables = await workspace.variables()
    if not variables:
        return "the kernel has no variables", "listed variables, none"
    rows = [f"{v.name}\t{v.type}\t{v.shape}\t{v.preview}" for v in variables]
    return "name\ttype\tshape\tpreview\n" + "\n".join(rows), (f"listed {len(variables)} variables")


async def _inspect(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    expression = _string(args, "expression").strip()
    if not expression:
        raise BadInput("expression is empty")
    ok, text = await workspace.evaluate(expression)
    if len(text) > REPR_LIMIT:
        text = text[:REPR_LIMIT] + f"\n… cut at {REPR_LIMIT} characters"
    if not ok:
        return f"the expression raised: {text}", f"inspected `{expression}`, which raised"
    return text, f"inspected `{expression}`"


async def _peek_file(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    count = _integer(args, "lines", PEEK_LINES)
    count = max(1, min(count, PEEK_MAX_LINES))
    path = Path(_string(args, "path")).expanduser()
    if not path.is_absolute():
        path = workspace.cwd / path
    if not path.is_file():
        raise BadInput(f"{path} is not a file")
    with path.open("rb") as file:
        head = file.read(PEEK_MAX_BYTES + 1)
    if b"\0" in head:
        raise BadInput(f"{path} is not a text file")
    cut = len(head) > PEEK_MAX_BYTES
    lines = head[:PEEK_MAX_BYTES].decode("utf-8", errors="replace").splitlines()
    if cut and lines:
        lines.pop()  # the last line was cut mid-way
    shown = lines[:count]
    size = path.stat().st_size
    header = f"{path} ({size} bytes), first {len(shown)} lines:\n"
    return header + "\n".join(shown), f"read the first {len(shown)} lines of {path.name}"


async def _read_console(workspace: Workspace, args: dict[str, Any]) -> tuple[str, str]:
    count = max(1, min(_integer(args, "lines", CONSOLE_LINES), CONSOLE_MAX_LINES))
    text = workspace.console_tail(count)
    return text or "the console is empty", "read the console"


Tool = Callable[[Workspace, dict[str, Any]], Awaitable[tuple[str, str]]]

TOOLS: dict[str, Tool] = {
    "read_buffer": _read_buffer,
    "insert_cells": _insert_cells,
    "replace_lines": _replace_lines,
    "list_variables": _list_variables,
    "inspect": _inspect,
    "peek_file": _peek_file,
    "read_console": _read_console,
}
