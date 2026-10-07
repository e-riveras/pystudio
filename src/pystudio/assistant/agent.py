"""The loop: ask the model, run the tools it calls, hand back the results."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pystudio.assistant import tools
from pystudio.assistant.provider import (
    Provider,
    ProviderError,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnEnd,
)

Reason = Literal["done", "tools", "refused", "truncated"]

MAX_ROUNDS = 25
"""Requests one question may take before the assistant is stopped."""

SYSTEM = """\
You are the assistant inside pystudio, a terminal IDE for Python data science. The user \
works in a Neovim buffer made of cells, each starting with a `# %%` marker, and sends \
cells to a Jupyter kernel themselves. They ask you for analysis code in plain language: \
exploratory analysis of a file, a regression, a Bayesian model with MCMC.

Your job is to write that code into their editor with the insert_cells tool. Code belongs \
in the editor, never in the chat. You do not run it: the user does, with their own keys, \
so never say that something ran or report results you have not seen.

Look before you write. Read the buffer so new code reuses the imports, names and data \
already there. When the request is about data, look at it first, with list_variables and \
inspect if it is loaded, or peek_file if it is only a path: real column names and types \
make the difference between code that runs and code that guesses. inspect runs in the \
user's live session, so use it only to look.

Write cells the way a careful analyst would: imports in their own first cell unless the \
buffer already has them, one step per cell, a short title on each, and comments only \
where a choice needs explaining. Prefer the libraries the buffer already uses. If a \
library the code needs may not be installed, say so in the chat.

To change code that exists, read the buffer again and use replace_lines. When the user \
reports an error, read the console before guessing.

Finish with a few plain sentences in the chat: what you added, which cell to run first, \
and anything you assumed. If the request leaves a choice open that changes the code, \
make the reasonable choice and name it instead of asking.\
"""


@dataclass(frozen=True)
class ToolNote:
    """One line for the chat saying what a tool just did."""

    text: str


@dataclass(frozen=True)
class Notice:
    """Something the user should know that the model did not say."""

    text: str


Shown = TextDelta | ToolNote | Notice | TurnEnd


class Assistant:
    """One conversation, and the workspace its tools act on."""

    def __init__(
        self,
        provider: Provider,
        workspace: tools.Workspace,
        show: Callable[[Shown], None],
    ) -> None:
        self.workspace = workspace
        self.show = show
        self.conversation = provider.start(SYSTEM, tools.SPECS)
        # The tool calls the model is waiting on, and the results so far. A
        # turn that is cancelled or fails leaves them here, and the next
        # question has to answer every one of them first.
        self._calls: list[ToolCall] = []
        self._results: list[ToolResult] = []

    async def ask(self, text: str) -> None:
        """Answer one question, running tools until the model is done."""
        user: str | None = text
        answered = {result.id for result in self._results}
        results = self._results + [
            ToolResult(call.id, "not run: the turn was interrupted", is_error=True)
            for call in self._calls
            if call.id not in answered
        ]
        try:
            for _ in range(MAX_ROUNDS):
                calls: list[ToolCall] = []
                reason: Reason = "done"
                async for event in self.conversation.send(user=user, results=results):
                    if isinstance(event, TextDelta):
                        self.show(event)
                    elif isinstance(event, ToolCall):
                        calls.append(event)
                    else:
                        reason = event.reason
                self._calls, self._results = calls, []
                if reason != "tools":
                    self.show(TurnEnd(reason))
                    return
                user, results = None, self._results
                for call in calls:
                    result, note = await tools.run(self.workspace, call)
                    results.append(result)
                    self.show(ToolNote(note))
            self.show(Notice(f"stopped after {MAX_ROUNDS} rounds; ask again to continue"))
        except ProviderError as error:
            self.show(Notice(str(error)))
        except asyncio.CancelledError:
            self.show(Notice("cancelled"))
            raise
