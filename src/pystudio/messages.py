"""Textual messages posted by the kernel layer and the Neovim layer.

Both RPC layers are plain asyncio objects that know nothing about widgets. They
translate what arrives on the wire into one of the messages below and hand it to
a sink callback, which the app sets to ``self.post_message``. Panes then react
through ordinary Textual handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from textual.message import Message

from pystudio.introspect import Variable

KernelState = Literal["starting", "idle", "busy", "restarting", "dead"]


# --------------------------------------------------------------------------- kernel


@dataclass
class KernelStatus(Message):
    """Kernel execution state changed."""

    state: KernelState


@dataclass
class ExecuteInput(Message):
    """The kernel echoed back code it is about to run."""

    code: str
    execution_count: int


@dataclass
class StreamOutput(Message):
    """Text written to the kernel's stdout or stderr."""

    name: str
    text: str


@dataclass
class ExecuteResult(Message):
    """Value of the last expression in an execution."""

    execution_count: int
    data: dict[str, Any]


@dataclass
class DisplayData(Message):
    """Rich output published by the kernel, such as a matplotlib figure."""

    data: dict[str, Any]
    display_id: str | None = None
    update: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KernelError(Message):
    """An exception escaped an execution."""

    ename: str
    evalue: str
    traceback: list[str] = field(default_factory=list)


@dataclass
class ClearOutput(Message):
    """The kernel asked for previous output to be cleared."""

    wait: bool = False


@dataclass
class InputRequest(Message):
    """The kernel is blocked on ``input()``."""

    prompt: str
    password: bool = False


@dataclass
class VariablesSnapshot(Message):
    """A full picture of the user namespace, taken after execution settled."""

    variables: list[Variable] = field(default_factory=list)


# ----------------------------------------------------------------------------- nvim


class NvimRedraw(Message):
    """The embedded Neovim flushed a batch of redraw events.

    Carries no payload: the grid is mutated in place before this is posted, so
    the pane only needs to know that repainting is now allowed.
    """


@dataclass
class NvimSendRequest(Message):
    """``send.lua`` asked for these lines to be run in the kernel."""

    lines: list[str]


@dataclass
class NvimSendCells(Message):
    """``send.lua`` asked for cells to be run one after another, stopping at a failure.

    Each cell is the line its marker is on and its code.
    """

    cells: list[tuple[int, list[str]]]


@dataclass
class NvimEvent(Message):
    """Any other notification from the embedded Neovim."""

    method: str
    args: list[Any] = field(default_factory=list)


@dataclass
class NvimExited(Message):
    """The embedded Neovim process is gone."""

    returncode: int
