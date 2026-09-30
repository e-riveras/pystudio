"""The console: a transcript, and a prompt that knows about unfinished blocks."""

from __future__ import annotations

import codeop
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, RichLog

HISTORY_LIMIT = 1000

PROMPT = "In [{count}]: "
CONTINUATION = "   ...: "
RESULT = "Out[{count}]: "


def history_path() -> Path:
    """Where the prompt history lives, following the XDG state convention."""
    state = os.environ.get("XDG_STATE_HOME")
    root = Path(state) if state else Path.home() / ".local" / "state"
    return root / "pystudio" / "history"


class ConsolePane(Vertical):
    """Kernel output above, prompt below."""

    DEFAULT_CSS = """
    ConsolePane {
        layout: vertical;
    }
    ConsolePane > RichLog {
        height: 1fr;
        background: transparent;
    }
    ConsolePane > Input {
        height: 1;
        border: none;
        padding: 0;
        background: transparent;
    }
    """

    @dataclass
    class Submitted(Message):
        """The user finished a block at the prompt."""

        code: str

    @dataclass
    class InputAnswered(Message):
        """The user answered a kernel ``input()`` request."""

        text: str

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._block: list[str] = []
        self._history: list[str] = []
        self._history_index = 0
        self.awaiting_input: str | None = None

    def compose(self):
        yield RichLog(id="console-log", wrap=True, markup=False, highlight=False, max_lines=5000)
        yield Input(id="console-prompt", placeholder="python")

    def on_mount(self) -> None:
        self._load_history()

    def on_unmount(self) -> None:
        self._save_history()

    # ------------------------------------------------------------------- transcript

    @property
    def log_widget(self) -> RichLog:
        return self.query_one("#console-log", RichLog)

    @property
    def prompt(self) -> Input:
        return self.query_one("#console-prompt", Input)

    def write(self, renderable: Text | str) -> None:
        self.log_widget.write(renderable)

    def show_code(self, code: str, count: int) -> None:
        """Echo executed code the way IPython does, continuation lines included."""
        lines = code.splitlines() or [""]
        first = Text(PROMPT.format(count=count or " "), style="bold green")
        first.append(lines[0], style="default")
        self.write(first)
        for line in lines[1:]:
            continuation = Text(CONTINUATION, style="green")
            continuation.append(line, style="default")
            self.write(continuation)

    def show_result(self, text: str, count: int) -> None:
        label = Text(RESULT.format(count=count or " "), style="bold blue")
        label.append(text)
        self.write(label)

    def show_stream(self, name: str, text: str) -> None:
        style = "red" if name == "stderr" else "default"
        self.write(Text(text.rstrip("\n"), style=style))

    def show_traceback(self, traceback: list[str]) -> None:
        for chunk in traceback:
            for line in chunk.splitlines():
                self.write(Text.from_ansi(line))

    def show_note(self, text: str) -> None:
        self.write(Text(text, style="dim italic"))

    def clear_log(self) -> None:
        self.log_widget.clear()

    # ----------------------------------------------------------------------- prompt

    def ask_for_input(self, prompt: str, password: bool) -> None:
        """Turn the prompt into an answer box for a kernel ``input()`` call."""
        self.awaiting_input = prompt
        widget = self.prompt
        widget.password = password
        widget.placeholder = prompt or "input"
        widget.focus()

    def _reset_prompt(self) -> None:
        widget = self.prompt
        widget.password = False
        widget.placeholder = CONTINUATION.strip() if self._block else "python"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value
        self.prompt.value = ""

        if self.awaiting_input is not None:
            shown = "*" * len(value) if self.prompt.password else value
            self.show_note(f"{self.awaiting_input}{shown}")
            self.awaiting_input = None
            self._reset_prompt()
            self.post_message(self.InputAnswered(value))
            return

        self._block.append(value)
        source = "\n".join(self._block)
        # An empty line ends a block, the way it does in the Python REPL.
        finished = (not value.strip() and len(self._block) > 1) or self._is_complete(source)
        if not finished:
            self._reset_prompt()
            return

        self._block.clear()
        self._reset_prompt()
        code = source.strip("\n")
        if not code.strip():
            return
        self._remember(code)
        self.post_message(self.Submitted(code))

    @staticmethod
    def _is_complete(source: str) -> bool:
        stripped = source.lstrip()
        if not stripped:
            return True
        # Magics, shell escapes and `obj?` are not Python, so let the kernel judge.
        if stripped.startswith(("%", "!", "?")) or stripped.rstrip().endswith("?"):
            return True
        try:
            return codeop.compile_command(source + "\n", "<console>", "exec") is not None
        except SyntaxError:
            return True

    # ---------------------------------------------------------------------- history

    def _remember(self, code: str) -> None:
        if not code or (self._history and self._history[-1] == code):
            self._history_index = len(self._history)
            return
        self._history.append(code)
        del self._history[:-HISTORY_LIMIT]
        self._history_index = len(self._history)

    def on_key(self, event) -> None:
        if not self.prompt.has_focus or event.key not in ("up", "down"):
            return
        if not self._history:
            return
        event.stop()
        event.prevent_default()
        if event.key == "up":
            self._history_index = max(0, self._history_index - 1)
        else:
            self._history_index = min(len(self._history), self._history_index + 1)
        widget = self.prompt
        if self._history_index >= len(self._history):
            widget.value = ""
        else:
            widget.value = self._history[self._history_index]
        widget.cursor_position = len(widget.value)

    def _load_history(self) -> None:
        path = history_path()
        if not path.exists():
            return
        with contextlib.suppress(OSError):
            entries = [line for line in path.read_text(encoding="utf-8").split("\0") if line]
            self._history = entries[-HISTORY_LIMIT:]
            self._history_index = len(self._history)

    def _save_history(self) -> None:
        path = history_path()
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\0".join(self._history), encoding="utf-8")
