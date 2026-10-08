"""The terminal pane, running real programs on a real pty."""

from __future__ import annotations

import asyncio
import sys
import time

from textual.app import App, ComposeResult

from pystudio.widgets.terminal import TerminalPane, rich_color

PY = sys.executable


class Host(App):
    def compose(self) -> ComposeResult:
        yield TerminalPane(id="term")

    @property
    def term(self) -> TerminalPane:
        return self.query_one(TerminalPane)


async def until(predicate, *, timeout: float = 10.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{what} never became true within {timeout}s")


ECHO = """
import sys, tty
tty.setraw(0)
while True:
    data = sys.stdin.buffer.read1(100)
    if not data or data == b"q":
        break
    sys.stdout.write(repr(data) + "\\r\\n")
    sys.stdout.flush()
"""


def test_colour_names() -> None:
    assert rich_color("default") is None
    assert rich_color("ff0000") == "#ff0000"
    assert rich_color("brown") == "yellow"
    assert rich_color("brightred") == "bright_red"


async def test_output_is_drawn_with_its_colours() -> None:
    app = Host()
    async with app.run_test(size=(60, 10)):
        term = app.term
        await term.start([PY, "-c", "print('\\x1b[38;2;255;0;0mred\\x1b[0m plain')"])
        await until(lambda: "red plain" in term.text, what="the output")
        assert term.screen_model.buffer[0][0].fg == "ff0000"
        await until(lambda: not term.running, what="the exit")
        await until(lambda: "exited (0)" in term.notice, what="the exit notice")


async def test_keys_reach_the_program() -> None:
    app = Host()
    async with app.run_test(size=(60, 10)) as pilot:
        term = app.term
        term.focus()
        await term.start([PY, "-c", ECHO])
        await asyncio.sleep(0.3)
        await pilot.press("x", "ctrl+c", "up")
        await until(lambda: "b'\\x1b[A'" in term.text, what="the arrow")
        assert "b'x'" in term.text
        assert "b'\\x03'" in term.text
        await pilot.press("q")
        await until(lambda: not term.running, what="the exit")


async def test_the_program_sees_the_pane_size_and_its_changes() -> None:
    script = (
        "import os, signal, time\n"
        "print(os.get_terminal_size(), flush=True)\n"
        "signal.signal(signal.SIGWINCH, lambda *a: print(os.get_terminal_size(), flush=True))\n"
        "time.sleep(5)\n"
    )
    app = Host()
    async with app.run_test(size=(60, 10)) as pilot:
        term = app.term
        await term.start([PY, "-c", script])
        await until(lambda: "columns=60, lines=10" in term.text, what="the first size")
        await pilot.resize_terminal(70, 12)
        await until(lambda: "columns=70, lines=12" in term.text, what="the new size")
        await term.stop()
        assert not term.running


async def test_paste_is_bracketed_only_when_asked_for() -> None:
    script = "import sys\nsys.stdout.write('\\x1b[?2004h'); sys.stdout.flush()\n" + ECHO
    app = Host()
    async with app.run_test(size=(80, 10)) as pilot:
        term = app.term
        term.focus()
        await term.start([PY, "-c", script])
        await asyncio.sleep(0.3)
        from textual import events

        term.post_message(events.Paste("hi\nthere"))
        await until(lambda: "200~" in term.text, what="the paste")
        assert "hi\\rthere" in term.text
        await pilot.press("q")


async def test_a_missing_program_is_a_notice() -> None:
    app = Host()
    async with app.run_test(size=(60, 10)):
        await app.term.start(["/no/such/agent"])
        assert "could not start" in app.term.notice
        assert not app.term.running


async def test_enter_restarts_an_exited_program(tmp_path) -> None:
    runs = tmp_path / "runs"
    script = f"open({str(runs)!r}, 'a').write('run\\n')"
    app = Host()
    async with app.run_test(size=(60, 10)) as pilot:
        term = app.term
        term.focus()
        await term.start([PY, "-c", script])
        await until(lambda: not term.running and "exited" in term.notice, what="the exit")
        await pilot.press("enter")
        await until(
            lambda: runs.exists() and runs.read_text().count("run") == 2, what="a second run"
        )


async def test_sequences_pyte_cannot_parse_leave_no_trace() -> None:
    script = "import sys\nsys.stdout.write('\\x1b[>5u\\x1b[?u\\x1b[>4;2m\\x1b[>0qclean\\x1b[<u')"
    app = Host()
    async with app.run_test(size=(60, 10)):
        term = app.term
        await term.start([PY, "-c", script])
        await until(lambda: "clean" in term.text, what="the output")
        assert term.text.strip() == "clean"


def test_a_sequence_split_across_reads_is_kept_whole() -> None:
    term = TerminalPane()
    term._feed(b"a\x1b[>")
    term._feed(b"5ub")
    assert term.text.strip() == "ab"


async def test_named_variables_are_kept_from_the_program(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_FOR_TEST", "leaked")
    script = "import os; print('value:', os.environ.get('SECRET_FOR_TEST'), os.environ.get('X'))"
    app = Host()
    async with app.run_test(size=(60, 10)):
        term = app.term
        await term.start([PY, "-c", script], env={"X": "given"}, without_env=["SECRET_FOR_TEST"])
        await until(lambda: "value: None given" in term.text, what="the environment")
