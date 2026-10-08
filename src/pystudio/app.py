"""The app: four panes, one kernel, one embedded Neovim.

Neovim owns its entire keyspace, so app-level keys live behind a ``ctrl+g``
chord. The chord keys are registered as priority bindings, which Textual checks
before the focused widget, and ``check_action`` keeps them disabled until the
chord is actually pending. A disabled binding does not consume the key, so `1`
still reaches Neovim, or the console prompt, the rest of the time.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher
from textual.worker import Worker

from pystudio import assistant as ai
from pystudio import messages as m
from pystudio.agents import Agent, choose
from pystudio.assistant.bridge import Bridge
from pystudio.assistant.workspace import AppWorkspace
from pystudio.interpreter import KernelChoice, candidates, has_ipykernel
from pystudio.introspect import Variable
from pystudio.kernel import KernelReset, KernelSession
from pystudio.widgets import (
    PROTOCOL,
    AssistantPane,
    ConsolePane,
    FrameViewer,
    KernelPicker,
    NvimPane,
    PlotsPane,
    StatusBar,
    VariablesPane,
)

if TYPE_CHECKING:
    from pystudio.widgets.terminal import TerminalPane

log = logging.getLogger(__name__)

PROBE_DELAY = 0.1
"""Wait a beat before snapshotting variables, so a burst of cells costs one probe."""

VIEWABLE_TYPES = {"DataFrame", "Series", "ndarray"}
"""Types the table viewer opens on `enter`; anything else prints to the console."""

TWO_DIMENSIONAL = re.compile(r"^\(\d+, \d+\)$")

ASSISTANT_OFF = "the assistant is off; start pystudio with --assistant"
AGENT_OFF = "the agent pane is off; start pystudio with --agent"

DOCKED = ("console", "assistant")
"""The panes that share the bottom-left slot, one shown at a time."""

PANE_TITLES = {
    "editor": "editor",
    "console": "console",
    "assistant": "assistant",
    "variables": "variables",
    "plots": "plots",
}


def while_running[M](
    handler: Callable[[PyStudioApp, M], None],
) -> Callable[[PyStudioApp, M], None]:
    """Drop a kernel message that arrives once the app has begun shutting down.

    Kernel messages keep coming while the kernel shuts down, and Textual drains
    the queue after the panes are gone, so a late status would find no widget
    to update.
    """

    @wraps(handler)
    def guarded(app: PyStudioApp, message: M) -> None:
        if app.is_running:
            handler(app, message)

    return guarded


class PyStudioApp(App):
    """A terminal IDE for Python data science."""

    CSS_PATH = "app.tcss"
    TITLE = "pystudio"

    BINDINGS = [
        Binding("ctrl+g", "start_chord", "global keys", priority=True, show=False),
        Binding("1", "chord_focus('editor')", "editor", priority=True, show=False),
        Binding("2", "chord_focus('console')", "console", priority=True, show=False),
        Binding("3", "chord_focus('variables')", "variables", priority=True, show=False),
        Binding("4", "chord_focus('plots')", "plots", priority=True, show=False),
        Binding("a", "chord_focus('assistant')", "assistant", priority=True, show=False),
        Binding("z", "chord_zoom", "zoom pane", priority=True, show=False),
        Binding("r", "chord_restart", "restart kernel", priority=True, show=False),
        Binding("i", "chord_interrupt", "interrupt kernel", priority=True, show=False),
        Binding("k", "chord_kernels", "switch kernel", priority=True, show=False),
        Binding("c", "chord_agent", "coding agent", priority=True, show=False),
        Binding("q", "chord_quit", "quit", priority=True, show=False),
        Binding("escape", "chord_cancel", "cancel", priority=True, show=False),
    ]

    def __init__(
        self,
        *,
        path: Path | None = None,
        clean: bool = False,
        nvim: str = "nvim",
        kernel_name: str = "python3",
        choice: KernelChoice | None = None,
        assistant: ai.Provider | str | None = None,
        agent: Agent | str | None = None,
    ) -> None:
        """``assistant`` and ``agent`` turn the two AI features on; both are off by default.

        ``assistant`` is a provider or the name of one, ``agent`` an agent or
        the name of one.
        """
        super().__init__()
        self.path = path
        self.clean = clean
        self.nvim_executable = nvim
        self.choice = choice or KernelChoice(kernel_name=kernel_name, label=kernel_name)
        self.cwd = path.parent if path is not None else Path.cwd()
        self.kernel = self._session(self.choice)
        self._chord = False
        self._probe_timer = None
        self._kernel_ready = False
        self._switching = False
        self._quitting = False
        self._provider = assistant
        self._assistant: ai.Assistant | None = None
        self._asking: Worker[None] | None = None
        self._running_cells: Worker[None] | None = None
        self._agent = agent
        self._bridge: Bridge | None = None

    def _session(self, choice: KernelChoice) -> KernelSession:
        return KernelSession(
            self.post_message,
            kernel_name=choice.kernel_name,
            python=choice.python,
            connection_file=choice.connection_file,
            cwd=self.cwd,
        )

    # ------------------------------------------------------------------- structure

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            if self._agent is not None:
                # Imported here: the terminal needs pyte, an optional dependency.
                from pystudio.widgets.terminal import TerminalPane

                yield TerminalPane(id="agent")
            yield from self._panes()
        yield StatusBar(kernel_name=self.choice.label, protocol=PROTOCOL, id="status")

    def _panes(self) -> ComposeResult:
        with Container(id="panes"):
            yield NvimPane(
                id="editor",
                executable=self.nvim_executable,
                file=self.path,
                clean=self.clean,
            )
            yield VariablesPane(id="variables")
            with ContentSwitcher(id="dock", initial="console"):
                yield ConsolePane(id="console")
                if self._provider is not None:
                    yield AssistantPane(id="assistant")
            yield PlotsPane(id="plots")

    def on_mount(self) -> None:
        for pane_id, title in PANE_TITLES.items():
            # The assistant's pane exists only when the assistant is on.
            for pane in self.query(f"#{pane_id}"):
                pane.border_title = title
        self.editor.focus()
        self.run_worker(self._start_kernel(), name="kernel-start")

    async def _start_kernel(self) -> None:
        if self.choice.note:
            self.console_pane.show_note(self.choice.note)
        try:
            await self.kernel.start()
        except Exception as error:  # noqa: BLE001 - surfaced in the UI instead
            log.exception("kernel failed to start")
            await self.kernel.shutdown()
            self.console_pane.show_note(f"kernel failed to start: {error}; ctrl+g k picks another")
            self.status.set_state("dead")
            return
        self._kernel_ready = True

    async def on_unmount(self) -> None:
        if self._bridge is not None:
            await self._bridge.stop()
        if self._kernel_ready:
            await self.kernel.shutdown()

    # --------------------------------------------------------------------- shortcuts

    @property
    def editor(self) -> NvimPane:
        return self.query_one("#editor", NvimPane)

    @property
    def console_pane(self) -> ConsolePane:
        return self.query_one("#console", ConsolePane)

    @property
    def agent_pane(self) -> TerminalPane:
        from pystudio.widgets.terminal import TerminalPane

        return self.query_one("#agent", TerminalPane)

    @property
    def assistant_pane(self) -> AssistantPane:
        return self.query_one("#assistant", AssistantPane)

    @property
    def kernel_ready(self) -> bool:
        return self._kernel_ready

    @property
    def variables(self) -> VariablesPane:
        return self.query_one("#variables", VariablesPane)

    @property
    def plots(self) -> PlotsPane:
        return self.query_one("#plots", PlotsPane)

    @property
    def status(self) -> StatusBar:
        return self.query_one("#status", StatusBar)

    # ------------------------------------------------------------------- the chord

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "start_chord":
            return not self._chord
        if action.startswith("chord_"):
            return self._chord
        return True

    @property
    def chord_pending(self) -> bool:
        """Whether ``ctrl+g`` was pressed and the next key belongs to the chord."""
        return self._chord

    def action_start_chord(self) -> None:
        self._chord = True
        self.status.set_note("ctrl+g …")
        self.refresh_bindings()

    def cancel_chord(self) -> None:
        """Called by the editor pane whenever a key gets through to Neovim."""
        if not self._chord:
            return
        self._chord = False
        self.status.set_note(self._idle_note())
        self.refresh_bindings()

    def action_chord_cancel(self) -> None:
        self.cancel_chord()

    def _idle_note(self) -> str:
        """What the status bar says when no chord is pending."""
        return "assistant…" if self._asking is not None else ""

    def action_chord_focus(self, pane: str) -> None:
        self.cancel_chord()
        if pane == "assistant" and self._provider is None:
            self.status.set_note(ASSISTANT_OFF)
            return
        if pane in DOCKED:
            self.query_one("#dock", ContentSwitcher).current = pane
        target = self.query_one(f"#{pane}")
        if target.focusable:
            target.focus()
            return
        # Container panes, such as the console, focus their first focusable child.
        for child in target.query("*"):
            if child.focusable:
                child.focus()
                return

    def action_chord_zoom(self) -> None:
        self.cancel_chord()
        screen = self.screen
        if screen.maximized is not None:
            screen.minimize()
        elif self.focused is not None:
            screen.maximize(self.focused)

    def action_chord_interrupt(self) -> None:
        self.cancel_chord()
        if self._kernel_ready:
            self.run_worker(self.kernel.interrupt(), name="interrupt")

    def action_chord_restart(self) -> None:
        self.cancel_chord()
        if not self._kernel_ready:
            return
        if not self.kernel.owned:
            self.console_pane.show_note(
                "this kernel was started elsewhere, so it is not pystudio's to restart"
            )
            return
        self.console_pane.show_note("restarting kernel…")
        self.run_worker(self._restart(), name="restart")

    async def _restart(self) -> None:
        await self.kernel.restart()
        self.console_pane.show_note("kernel restarted")

    def action_chord_kernels(self) -> None:
        self.cancel_chord()
        if self._switching or isinstance(self.screen, ModalScreen):
            return
        choices = candidates(start=self.cwd, exclude=self.kernel.connection_file)
        if self.choice.target not in [choice.target for choice in choices]:
            choices.insert(0, self.choice)
        self.push_screen(KernelPicker(choices, self.choice), self._picked)

    def _picked(self, choice: KernelChoice | None) -> None:
        if choice is None or self._switching:
            return
        if choice.target == self.choice.target and self._kernel_ready:
            return
        self._switching = True
        self.run_worker(self._switch(choice), name="kernel-switch")

    async def _switch(self, choice: KernelChoice) -> None:
        """Replace the kernel. The old one keeps running until the new one can."""
        try:
            if choice.python is not None and not await asyncio.to_thread(
                has_ipykernel, choice.python
            ):
                self.console_pane.show_note(
                    f"{choice.label} has no ipykernel, so the kernel stays where it is. "
                    "Add it with: uv add --dev ipykernel"
                )
                return
            self.console_pane.show_note(f"switching kernel to {choice.label}…")
            self._kernel_ready = False
            await self.kernel.shutdown()
            self.choice = choice
            self.kernel = self._session(choice)
            self.status.set_kernel(choice.label)
            self.variables.show([])
            await self._start_kernel()
        finally:
            self._switching = False

    # ------------------------------------------------------------------ agent pane

    def action_chord_agent(self) -> None:
        """Open the agent column and focus it, or hide it when it has focus."""
        self.cancel_chord()
        if self._agent is None:
            self.status.set_note(AGENT_OFF)
            return
        pane = self.agent_pane
        if pane.display and pane.has_focus:
            pane.display = False
            self.editor.focus()
            return
        pane.display = True
        pane.focus()
        if not pane.running and not pane.argv:
            self.run_worker(self._start_agent(), name="agent")

    async def _start_agent(self) -> None:
        pane = self.agent_pane
        try:
            agent = self._agent if isinstance(self._agent, Agent) else choose(self._agent)
        except ValueError as error:
            pane.notice = str(error)
            pane.refresh()
            return
        pane.border_title = f"agent: {agent.name}"
        if self._bridge is None:
            self._bridge = Bridge(AppWorkspace(self))
        socket = await self._bridge.start()
        # Let the pane take its size before the agent asks for it.
        await asyncio.sleep(0)
        await pane.start(agent.command(socket), cwd=self.cwd, without_env=agent.without_env)

    def on_descendant_focus(self, event) -> None:
        # The agent reads files from disk, so it should see what the user sees.
        if event.widget.id == "agent" and self.editor.rpc.running:
            self.editor.rpc.notify("nvim_command", "silent! wall")

    def action_chord_quit(self) -> None:
        self.cancel_chord()
        self._quitting = True
        # Let Neovim raise its own prompt about unsaved buffers.
        self.run_worker(self._quit(), name="quit")

    async def _quit(self) -> None:
        if self.editor.rpc.running:
            await self.editor.request_quit()
            return
        self.exit()

    # -------------------------------------------------------------- kernel messages

    @while_running
    def on_kernel_status(self, message: m.KernelStatus) -> None:
        self.status.set_state(message.state)
        self.editor.publish_kernel_state(message.state)
        if message.state == "dead":
            how = "ctrl+g r restarts it" if self.kernel.owned else "ctrl+g k picks another"
            self.console_pane.show_note(f"kernel died; {how}")
        if message.state == "idle":
            self._schedule_probe()

    @while_running
    def on_execute_input(self, message: m.ExecuteInput) -> None:
        self.console_pane.show_code(message.code, message.execution_count)

    @while_running
    def on_stream_output(self, message: m.StreamOutput) -> None:
        self.console_pane.show_stream(message.name, message.text)

    @while_running
    def on_execute_result(self, message: m.ExecuteResult) -> None:
        text = message.data.get("text/plain", "")
        self.console_pane.show_result(text, message.execution_count)

    @while_running
    def on_display_data(self, message: m.DisplayData) -> None:
        png = message.data.get("image/png")
        if png is not None:
            self.plots.add(_decode_png(png))
            return
        text = message.data.get("text/plain")
        if text:
            self.console_pane.write(Text(text))

    @while_running
    def on_kernel_error(self, message: m.KernelError) -> None:
        if message.traceback:
            self.console_pane.show_traceback(message.traceback)
        else:
            self.console_pane.show_stream("stderr", f"{message.ename}: {message.evalue}")

    @while_running
    def on_clear_output(self, message: m.ClearOutput) -> None:
        self.console_pane.clear_log()

    @while_running
    def on_input_request(self, message: m.InputRequest) -> None:
        self.console_pane.ask_for_input(message.prompt, message.password)

    @while_running
    def on_variables_snapshot(self, message: m.VariablesSnapshot) -> None:
        self.variables.show(message.variables)

    def _schedule_probe(self) -> None:
        if not self._kernel_ready:
            return
        if self._probe_timer is not None:
            self._probe_timer.stop()
        self._probe_timer = self.set_timer(PROBE_DELAY, self._probe)

    def _probe(self) -> None:
        self._probe_timer = None
        if self._kernel_ready:
            self.run_worker(self.kernel.probe_variables(), name="probe")

    # ------------------------------------------------------------------ ui messages

    def on_console_pane_submitted(self, message: ConsolePane.Submitted) -> None:
        self._execute(message.code)

    def on_console_pane_input_answered(self, message: ConsolePane.InputAnswered) -> None:
        if self._kernel_ready:
            self.kernel.send_input(message.text)

    def on_console_pane_complete_requested(self, message: ConsolePane.CompleteRequested) -> None:
        if self._kernel_ready:
            self.run_worker(self._complete(message.code, message.cursor_pos), name="complete")

    async def _complete(self, code: str, cursor_pos: int) -> None:
        try:
            reply = await self.kernel.complete(code, cursor_pos)
        except TimeoutError:
            return
        if reply.get("status") != "ok":
            return
        self.console_pane.apply_completion(
            [str(match) for match in reply.get("matches", ())],
            int(reply.get("cursor_start", cursor_pos)),
            int(reply.get("cursor_end", cursor_pos)),
        )

    def on_variables_pane_inspect(self, message: VariablesPane.Inspect) -> None:
        variable = message.variable
        if self._kernel_ready and self._is_viewable(variable):
            self.push_screen(FrameViewer(variable, self.kernel.fetch_frame))
            return
        self._execute(variable.name)

    @staticmethod
    def _is_viewable(variable: Variable) -> bool:
        return variable.type in VIEWABLE_TYPES or bool(TWO_DIMENSIONAL.match(variable.shape))

    # -------------------------------------------------------------------- assistant

    def on_assistant_pane_asked(self, message: AssistantPane.Asked) -> None:
        pane = self.assistant_pane
        if self._asking is not None:
            pane.show_note("still working on the last request; escape cancels it")
            return
        pane.show_user(message.text)
        self._asking = self.run_worker(self._ask(message.text), name="assistant")
        self.status.set_note(self._idle_note())

    def on_assistant_pane_cancelled(self, message: AssistantPane.Cancelled) -> None:
        if self._asking is not None:
            self._asking.cancel()

    async def _ask(self, text: str) -> None:
        try:
            if self._assistant is None:
                provider = self._provider
                if isinstance(provider, str):
                    provider = ai.load(provider)
                self._assistant = ai.Assistant(provider, AppWorkspace(self), self._shown)
            await self._assistant.ask(text)
        except ai.ProviderError as error:
            self.assistant_pane.show_note(str(error))
        finally:
            self._asking = None
            if self.is_running:
                self.assistant_pane.end_reply()
                self.status.set_note("ctrl+g …" if self._chord else "")

    def _shown(self, event: ai.TextDelta | ai.ToolNote | ai.Notice | ai.TurnEnd) -> None:
        """Put one step of the assistant's turn into the chat."""
        if not self.is_running:
            return
        pane = self.assistant_pane
        if isinstance(event, ai.TextDelta):
            pane.stream(event.text)
        elif isinstance(event, ai.ToolNote | ai.Notice):
            pane.show_note(event.text)
        elif event.reason == "refused":
            pane.show_note("the model declined this request")
        elif event.reason == "truncated":
            pane.show_note("the reply was cut off at the length limit; ask it to continue")

    def on_nvim_send_request(self, message: m.NvimSendRequest) -> None:
        self._execute("\n".join(message.lines))

    def on_nvim_send_cells(self, message: m.NvimSendCells) -> None:
        if not self._kernel_ready:
            self.console_pane.show_note("kernel is still starting…")
            return
        if self._running_cells is not None:
            self.console_pane.show_note("still running cells; ctrl+g i interrupts them")
            return
        self._running_cells = self.run_worker(self._run_cells(message.cells), name="cells")

    async def _run_cells(self, cells: list[tuple[int, list[str]]]) -> None:
        """Run cells one at a time, and stop at the first that does not succeed."""
        try:
            for index, (line, lines) in enumerate(cells):
                try:
                    status = await self.kernel.run("\n".join(lines))
                except KernelReset as reason:
                    self.console_pane.show_note(f"stopped running cells: {reason}")
                    return
                if status != "ok":
                    left = len(cells) - index - 1
                    after = (
                        f"; {left} cell{'s' if left != 1 else ''} after it not run" if left else ""
                    )
                    self.console_pane.show_note(f"stopped at the cell on line {line}{after}")
                    return
        finally:
            self._running_cells = None

    def on_nvim_event(self, message: m.NvimEvent) -> None:
        if message.method == "pystudio_control":
            what = str(message.args[0]) if message.args else ""
            if what == "interrupt":
                self.action_chord_interrupt()
            elif what == "restart":
                self.action_chord_restart()
            return
        if message.method == "pystudio_buffer":
            self.status.set_filename(str(message.args[0]) if message.args else "")

    def on_nvim_exited(self, message: m.NvimExited) -> None:
        self.exit()

    def _execute(self, code: str) -> None:
        if not code.strip():
            return
        if not self._kernel_ready:
            self.console_pane.show_note("kernel is still starting…")
            return
        self.run_worker(self.kernel.execute(code), name="execute")


def _decode_png(payload: object) -> bytes:
    """``image/png`` arrives base64 encoded, unless a transport already decoded it."""
    import base64

    if isinstance(payload, bytes):
        return payload
    return base64.b64decode(str(payload))
