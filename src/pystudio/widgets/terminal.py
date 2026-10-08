"""A terminal inside a pane: a child process on a pty, painted from pyte's screen.

It exists for coding agents such as Claude Code, which are full terminal
programs with their own UI. Running the real CLI keeps its login, its slash
commands and its prompts exactly as they are in any other terminal.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import pty
import re
import signal
import struct
import termios
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyte
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

from pystudio.terminal_keys import key_to_bytes

log = logging.getLogger(__name__)

HISTORY = 5000
"""Lines of scrollback kept above the screen."""

READ_SIZE = 65536

BRACKETED_PASTE = 2004 << 5
APPLICATION_CURSOR = 1 << 5
ALTERNATE_SCREENS = {47 << 5, 1047 << 5, 1049 << 5}
"""Private modes are stored shifted by pyte, to tell them from ANSI ones."""

FOCUS_EVENTS = 1004 << 5

UNSUPPORTED = re.compile(rb"\x1b\[(?:[<>=][0-9;]*[A-Za-z]|\?u)")
"""CSI sequences pyte cannot parse and would print the tail of: the kitty
keyboard protocol (``CSI > 5 u``, ``CSI < u``, ``CSI ? u``), modifyOtherKeys
(``CSI > 4 ; 2 m``) and XTVERSION (``CSI > 0 q``). Dropping them leaves the
program on plain xterm keys, since nothing answers its query."""

PARTIAL = re.compile(rb"\x1b(?:\[[<>=?0-9;]*)?$")
"""An escape sequence cut off at the end of a read, kept for the next one."""

NAMED = {"brown": "yellow", "brightbrown": "bright_yellow"}
"""pyte's colour names that Rich spells differently."""


def rich_color(value: str) -> str | None:
    if value == "default":
        return None
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        return f"#{value}"
    value = NAMED.get(value, value)
    if value.startswith("bright") and not value.startswith("bright_"):
        return "bright_" + value.removeprefix("bright")
    return value


class Screen(pyte.HistoryScreen):
    """pyte's screen, plus the few things a modern CLI needs from it."""

    def __init__(self, columns: int, lines: int, reply) -> None:
        super().__init__(columns, lines, history=HISTORY, ratio=0.5)
        self._reply = reply

    def write_process_input(self, data: str) -> None:
        # Answers to device queries, such as the cursor position, go back to
        # the program; some wait for them before they draw anything.
        self._reply(data.encode())

    def set_mode(self, *modes: int, **kwargs: Any) -> None:
        super().set_mode(*modes, **kwargs)
        if kwargs.get("private") and {mode << 5 for mode in modes} & ALTERNATE_SCREENS:
            # pyte has no second buffer. Starting from a clean one is what a
            # full-screen program expects, and what it gets back on exit.
            self.erase_in_display(2)
            self.cursor_position()

    def reset_mode(self, *modes: int, **kwargs: Any) -> None:
        super().reset_mode(*modes, **kwargs)
        if kwargs.get("private") and {mode << 5 for mode in modes} & ALTERNATE_SCREENS:
            self.erase_in_display(2)
            self.cursor_position()


class TerminalPane(Widget, can_focus=True):
    """Runs one program on a pty. Started on demand, restarted with enter once it exits."""

    @dataclass
    class Exited(Message):
        returncode: int

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.screen_model = Screen(80, 24, self._write)
        self.stream = pyte.ByteStream(self.screen_model)
        self.argv: list[str] = []
        self.env: dict[str, str] = {}
        self.cwd: Path | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._master: int | None = None
        self._waiter: asyncio.Task[None] | None = None
        self._carry = b""
        self.notice = ""

    # ------------------------------------------------------------------ lifecycle

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(
        self, argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] = {}
    ) -> None:
        """Start ``argv`` on a fresh pty, sized to the pane."""
        if self.running:
            return
        self.argv, self.cwd, self.env = list(argv), cwd, dict(env)
        columns, lines = max(self.size.width, 20), max(self.size.height, 5)
        self.screen_model = Screen(columns, lines, self._write)
        self.stream = pyte.ByteStream(self.screen_model)
        self._carry = b""
        self.notice = ""

        master, slave = pty.openpty()
        self._set_size(master, columns, lines)
        environment = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "COLUMNS": str(columns),
            "LINES": str(lines),
            **self.env,
        }
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.cwd,
                env=environment,
                start_new_session=True,
                preexec_fn=_take_terminal,
            )
        except OSError as error:
            os.close(master)
            self.notice = f"could not start {self.argv[0]}: {error.strerror or error}"
            self.refresh()
            return
        finally:
            os.close(slave)
        self._master = master
        os.set_blocking(master, False)
        asyncio.get_running_loop().add_reader(master, self._read)
        self._waiter = asyncio.create_task(self._wait(self.process), name="terminal-wait")
        self.refresh()

    async def stop(self) -> None:
        """End the program and its children, gently first."""
        process = self.process
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGHUP)
            try:
                await asyncio.wait_for(process.wait(), 2.0)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if self._waiter is not None:
            await asyncio.gather(self._waiter, return_exceptions=True)
        self._close_master()

    async def on_unmount(self) -> None:
        await self.stop()

    async def _wait(self, process: asyncio.subprocess.Process) -> None:
        returncode = await process.wait()
        # Output written just before exit is still in the pty.
        self._drain()
        self._close_master()
        self.notice = f"{Path(self.argv[0]).name} exited ({returncode}); enter starts it again"
        self.refresh()
        self.post_message(self.Exited(returncode))

    def _close_master(self) -> None:
        if self._master is None:
            return
        with contextlib.suppress(Exception):
            asyncio.get_running_loop().remove_reader(self._master)
        with contextlib.suppress(OSError):
            os.close(self._master)
        self._master = None

    # ------------------------------------------------------------------- the pty

    @staticmethod
    def _set_size(fd: int, columns: int, lines: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))

    def _read(self) -> None:
        if self._master is None:
            return
        try:
            data = os.read(self._master, READ_SIZE)
        except BlockingIOError:
            return
        except OSError:
            # EIO: every copy of the other end is closed; _wait finishes up.
            asyncio.get_running_loop().remove_reader(self._master)
            return
        if data:
            self._feed(data)
            self.refresh()

    def _feed(self, data: bytes) -> None:
        data = self._carry + data
        cut = PARTIAL.search(data)
        self._carry = data[cut.start() :] if cut else b""
        if cut:
            data = data[: cut.start()]
        self.stream.feed(UNSUPPORTED.sub(b"", data))

    def _drain(self) -> None:
        while self._master is not None:
            try:
                data = os.read(self._master, READ_SIZE)
            except OSError:
                return
            if not data:
                return
            self._feed(data)

    def _write(self, data: bytes) -> None:
        if self._master is None or not data:
            return
        view = memoryview(data)
        while view:
            try:
                written = os.write(self._master, view)
            except BlockingIOError:
                continue
            except OSError:
                return
            view = view[written:]

    # --------------------------------------------------------------------- input

    async def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        cancel = getattr(self.app, "cancel_chord", None)
        if cancel is not None:
            cancel()
        if not self.running:
            if event.key == "enter" and self.argv:
                await self.start(self.argv, cwd=self.cwd, env=self.env)
            return
        self._scroll_to_bottom()
        app_cursor = APPLICATION_CURSOR in self.screen_model.mode
        data = key_to_bytes(event.key, event.character, app_cursor=app_cursor)
        if data is not None:
            self._write(data)

    def on_paste(self, event: events.Paste) -> None:
        event.stop()
        event.prevent_default()
        text = event.text.replace("\r\n", "\r").replace("\n", "\r")
        if BRACKETED_PASTE in self.screen_model.mode:
            text = f"\x1b[200~{text}\x1b[201~"
        self._write(text.encode())

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.screen_model.prev_page()
        self.refresh()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.screen_model.next_page()
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.focus()

    def _scroll_to_bottom(self) -> None:
        history = self.screen_model.history
        if history.position < history.size:
            while self.screen_model.history.position < self.screen_model.history.size:
                before = self.screen_model.history.position
                self.screen_model.next_page()
                if self.screen_model.history.position == before:
                    break
            self.refresh()

    async def on_resize(self, event: events.Resize) -> None:
        columns, lines = max(self.size.width, 1), max(self.size.height, 1)
        if (columns, lines) == (self.screen_model.columns, self.screen_model.lines):
            return
        self.screen_model.resize(lines, columns)
        if self._master is not None:
            self._set_size(self._master, columns, lines)
        self.refresh()

    def on_focus(self) -> None:
        if FOCUS_EVENTS in self.screen_model.mode:
            self._write(b"\x1b[I")
        self.refresh()

    def on_blur(self) -> None:
        if FOCUS_EVENTS in self.screen_model.mode:
            self._write(b"\x1b[O")
        self.refresh()

    # ------------------------------------------------------------------- painting

    @property
    def text(self) -> str:
        """What is on the screen, as plain text."""
        return "\n".join(line.rstrip() for line in self.screen_model.display)

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        screen = self.screen_model
        if self.notice and y == self.size.height - 1:
            return Strip(
                [Segment(self.notice[:width], Style(dim=True, italic=True))]
            ).adjust_cell_length(width)
        if y >= screen.lines:
            return Strip.blank(width)
        row = screen.buffer[y]
        cursor = screen.cursor
        show_cursor = (
            self.has_focus
            and self.running
            and not cursor.hidden
            and y == cursor.y
            and screen.history.position >= screen.history.size
        )
        segments: list[Segment] = []
        for x in range(screen.columns):
            char = row[x]
            if char.data == "":
                continue  # the right half of a wide character
            style = _style(char, reverse=show_cursor and x == cursor.x)
            segments.append(Segment(char.data or " ", style))
        return Strip(Segment.simplify(segments)).adjust_cell_length(width)


def _style(char: Any, *, reverse: bool = False) -> Style:
    return Style(
        color=rich_color(char.fg),
        bgcolor=rich_color(char.bg),
        bold=char.bold or None,
        italic=char.italics or None,
        underline=char.underscore or None,
        strike=char.strikethrough or None,
        reverse=(char.reverse != reverse) or None,
    )


def _take_terminal() -> None:
    """In the child: make the pty, already on stdin, its controlling terminal."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
