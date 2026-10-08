"""The kernel layer: one Jupyter kernel, shared by the editor and the console.

``KernelSession`` owns an out-of-process kernel and one asyncio task per ZMQ
channel. Each task translates wire messages into :mod:`pystudio.messages`
objects and hands them to a sink callback. Nothing here imports a widget, so the
whole layer is testable without a UI.

A kernel started here listens on Unix domain sockets in a directory only the
user can enter, not on TCP. Jupyter signs its messages but does not encrypt
them, so on loopback ports any local user could subscribe to iopub and read
every output.

Shell requests go to the kernel one at a time, each after the reply to the one
before. The kernel would queue them itself, but ipykernel 7 can stop answering
the shell channel for good when requests reach it while a cell is running, and
the app sends plenty of its own: variable snapshots, table pages, figure renders.

The shell channel has exactly one consumer, this class. Request/reply pairs that
callers need to await (completion, inspection) are resolved through a futures
map keyed by ``msg_id``, rather than by reading the channel a second time, which
would let two consumers steal each other's replies.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jupyter_client.asynchronous.client import AsyncKernelClient
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from jupyter_client.manager import AsyncKernelManager
from textual.message import Message

from pystudio import messages as m
from pystudio.introspect import (
    PROBE_EXPR,
    SETUP,
    Frame,
    Variable,
    forget_expr,
    frame_expr,
    parse_frame,
    parse_probe,
    parse_render,
    render_expr,
    view_expr,
)

log = logging.getLogger(__name__)

Sink = Callable[[Message], None]

READY_TIMEOUT = 60.0
REQUEST_TIMEOUT = 5.0
FRAME_TIMEOUT = 15.0
ALIVE_POLL_SECONDS = 2.0
SOCKET_PATH_LIMIT = 90
"""Longest socket path prefix to accept; ``sun_path`` holds 104 bytes on macOS."""
TRACKED_IDS = 16
"""How many recent silent executions, quiet requests and probes stay tracked.

Shell replies and iopub messages travel on different channels, so a reply can
arrive before the ``idle`` status that belongs to the same request. Ids are
therefore forgotten by age rather than on reply, or that late status would leak
into the UI and retrigger the refresh it came from.
"""


class KernelReset(Exception):
    """The kernel restarted, died or was shut down while a reply was awaited."""


class InterpreterSpecs(KernelSpecManager):
    """Serves one kernelspec that runs ipykernel in a given interpreter."""

    def __init__(self, python: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.python = python

    def get_kernel_spec(self, kernel_name: str) -> KernelSpec:
        return KernelSpec(
            argv=[str(self.python), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            display_name=f"Python ({self.python})",
            language="python",
            metadata={"debugger": True},
        )


def socket_dir() -> Path:
    """A fresh directory for the kernel's sockets, readable by the user alone."""
    directory = Path(tempfile.mkdtemp(prefix="pystudio-"))
    if len(str(directory)) > SOCKET_PATH_LIMIT:
        directory.rmdir()
        directory = Path(tempfile.mkdtemp(prefix="pystudio-", dir="/tmp"))
    return directory


class KernelSession:
    """A running kernel plus the tasks that pump its channels.

    With ``connection_file`` set the session attaches to a kernel some other
    process started. It then owns the channels but not the process: shutting
    down leaves the kernel running, and restarting is not this session's call.
    """

    def __init__(
        self,
        sink: Sink,
        *,
        kernel_name: str = "python3",
        python: Path | None = None,
        connection_file: Path | None = None,
        cwd: Path | str | None = None,
    ) -> None:
        self.kernel_name = kernel_name
        self.python = python
        self.attach_to = connection_file
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.sink = sink
        self._sockets: Path | None = None
        self._km: AsyncKernelManager | None = None
        self._kc: AsyncKernelClient | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # Insertion-ordered, used as bounded sets.
        self._silent: dict[str, None] = {}  # hide the output
        self._quiet: dict[str, None] = {}  # hide the busy/idle churn too
        self._probes: dict[str, None] = {}  # and emit a snapshot on reply
        self._restarting = False
        self._closing = False
        # Requests not yet sent, and the id of the one the kernel is working on.
        self._queue: deque[dict[str, Any]] = deque()
        self._outstanding: str | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def client(self) -> AsyncKernelClient:
        if self._kc is None:
            raise RuntimeError("kernel is not started")
        return self._kc

    @property
    def owned(self) -> bool:
        """Whether this session started the kernel, rather than attaching to it."""
        return self.attach_to is None

    @property
    def connection_file(self) -> Path | None:
        """The running kernel's connection file, which another client can attach to."""
        if self.attach_to is not None:
            return self.attach_to
        return Path(self._km.connection_file) if self._km is not None else None

    async def start(self) -> None:
        """Launch or attach to the kernel, and install the introspection helper.

        With ``python`` set, the kernel runs in that interpreter rather than
        through the ``kernel_name`` kernelspec. If this raises, ``shutdown``
        still cleans up whatever was started.
        """
        self._emit(m.KernelStatus("starting"))
        if self.attach_to is not None:
            kc = AsyncKernelClient()
            kc.load_connection_file(str(self.attach_to))
        else:
            self._sockets = socket_dir()
            km = AsyncKernelManager(
                kernel_name=self.kernel_name, transport="ipc", ip=str(self._sockets / "k")
            )
            if self.python is not None:
                km.kernel_spec_manager = InterpreterSpecs(self.python)
            self._km = km
            await km.start_kernel(cwd=str(self.cwd))
            kc = km.client()
        self._kc = kc
        kc.start_channels()
        await kc.wait_for_ready(timeout=READY_TIMEOUT)

        self._tasks = [
            asyncio.create_task(self._pump(kc.get_iopub_msg, self._handle_iopub), name="iopub"),
            asyncio.create_task(self._pump(kc.get_shell_msg, self._handle_shell), name="shell"),
            asyncio.create_task(self._pump(kc.get_stdin_msg, self._handle_stdin), name="stdin"),
            asyncio.create_task(self._watch_alive(), name="alive"),
        ]
        await self._install_helper()

    async def shutdown(self) -> None:
        """Stop the pumps and the channels, and the kernel process if it is ours."""
        self._closing = True
        self._fail_pending("the kernel shut down")
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._kc is not None:
            self._kc.stop_channels()
        if self._km is not None:
            await self._km.shutdown_kernel(now=True)
        self._kc = self._km = None
        if self._sockets is not None:
            shutil.rmtree(self._sockets, ignore_errors=True)
            self._sockets = None

    async def restart(self) -> None:
        """Restart the kernel in place, keeping the same ports and channels."""
        if self._km is None:
            raise RuntimeError("kernel is not started, or is not ours to restart")
        self._restarting = True
        self._fail_pending("the kernel restarted")
        self._emit(m.KernelStatus("restarting"))
        try:
            await self._km.restart_kernel(now=False)
            await self._wait_ready()
        finally:
            self._restarting = False
        self._pending.clear()
        self._silent.clear()
        self._quiet.clear()
        self._probes.clear()
        await self._install_helper()
        self._emit(m.VariablesSnapshot([]))

    async def interrupt(self) -> None:
        """Send SIGINT (or the kernel's own interrupt mode) to the kernel."""
        if self._km is not None:
            await self._km.interrupt_kernel()
            return
        # Not our process to signal, so ask over the control channel instead.
        client = self.client
        client.control_channel.send(client.session.msg("interrupt_request", content={}))

    # -------------------------------------------------------------------- requests

    async def execute(
        self,
        code: str,
        *,
        silent: bool = False,
        store_history: bool = True,
    ) -> str:
        """Run ``code``. Output arrives later as messages. Returns the msg_id."""
        msg_id = self._execute_request(code, silent=silent, store_history=store_history)
        if silent:
            self._track(self._silent, msg_id)
        return msg_id

    async def run(self, code: str) -> str:
        """Run ``code`` like :meth:`execute`, and wait for it to finish.

        Returns the reply's status: ``ok``, ``error`` or ``aborted``. Raises
        :class:`KernelReset` if the kernel goes away first.
        """
        content = await self._await_reply(lambda: self._execute_request(code), timeout=None)
        return str(content.get("status", "error"))

    async def probe_variables(self) -> str:
        """Take a variable snapshot without touching history or producing output."""
        msg_id = self._execute_request(
            "",
            silent=True,
            store_history=False,
            user_expressions={"vars": PROBE_EXPR},
        )
        self._track(self._silent, msg_id)
        self._track(self._quiet, msg_id)
        self._track(self._probes, msg_id)
        return msg_id

    async def fetch_frame(
        self,
        name: str,
        start: int,
        stop: int,
        *,
        sort: str | None = None,
        ascending: bool = True,
    ) -> Frame:
        """Read one page of a DataFrame, Series or array, for the table viewer."""
        expression = frame_expr(name, start, stop, sort=sort, ascending=ascending)
        ok, text = await self.evaluate(expression)
        return parse_frame(text) if ok and text else Frame(kind="other")

    def set_plot_view(self, width: int, height: int) -> None:
        """Tell the kernel the size of the plot pane, so figures are drawn to fit it.

        Not awaited: the kernel serves requests in order, so the size is in
        place before anything sent after this runs.
        """
        self._send_expression(view_expr(width, height))

    def forget_figures(self, figures: list[int] | None = None) -> None:
        """Let the kernel drop figures it kept, all of them for ``None``."""
        self._send_expression(forget_expr(figures))

    async def render_figure(
        self,
        figure: int,
        room: tuple[int, int],
        window: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
        *,
        size: tuple[float, float] | None = None,
        fmt: str = "png",
    ) -> bytes | None:
        """Draw part of a figure the kernel kept, to fit ``room`` pixels.

        ``None`` means the kernel no longer has the figure. ``size`` lays the
        figure out again at that many inches first.
        """
        ok, text = await self.evaluate(render_expr(figure, room, window, size=size, fmt=fmt))
        return parse_render(text) if ok else None

    async def evaluate(self, expression: str, timeout: float = FRAME_TIMEOUT) -> tuple[bool, str]:
        """Evaluate one expression quietly: its repr, or the error it raised.

        Nothing reaches the console or the history. The kernel answers requests
        in order, so this waits behind whatever is running and may time out.
        """
        content = await self._await_reply(
            lambda: self._send_expression(expression), timeout=timeout
        )
        result: dict[str, Any] = (content.get("user_expressions") or {}).get("value") or {}
        if result.get("status") == "ok":
            return True, str((result.get("data") or {}).get("text/plain") or "")
        return False, f"{result.get('ename', 'Error')}: {result.get('evalue', '')}"

    async def variables(self) -> list[Variable]:
        """The user namespace, awaited, for callers that are not the variables pane."""
        ok, text = await self.evaluate(PROBE_EXPR)
        return parse_probe(text) if ok else []

    def _send_expression(self, expression: str) -> str:
        """Evaluate an expression quietly and return the request's msg_id."""
        msg_id = self._execute_request(
            "",
            silent=True,
            store_history=False,
            user_expressions={"value": expression},
        )
        self._track(self._silent, msg_id)
        self._track(self._quiet, msg_id)
        return msg_id

    async def complete(self, code: str, cursor_pos: int | None = None) -> dict[str, Any]:
        """Ask the kernel for completions at ``cursor_pos``."""
        position = len(code) if cursor_pos is None else cursor_pos
        return await self._await_reply(
            lambda: self._request("complete_request", {"code": code, "cursor_pos": position})
        )

    async def inspect(
        self, code: str, cursor_pos: int | None = None, detail_level: int = 0
    ) -> dict[str, Any]:
        """Ask the kernel for documentation at ``cursor_pos``."""
        return await self._await_reply(
            lambda: self._request(
                "inspect_request",
                {
                    "code": code,
                    "cursor_pos": len(code) if cursor_pos is None else cursor_pos,
                    "detail_level": detail_level,
                },
            )
        )

    # ------------------------------------------------------------ one request at a time

    def _execute_request(
        self,
        code: str,
        *,
        silent: bool = False,
        store_history: bool = True,
        user_expressions: dict[str, str] | None = None,
    ) -> str:
        return self._request(
            "execute_request",
            {
                "code": code,
                "silent": silent,
                "store_history": store_history,
                "user_expressions": user_expressions or {},
                "allow_stdin": self.client.allow_stdin,
                "stop_on_error": True,
            },
        )

    def _request(self, msg_type: str, content: dict[str, Any] | None = None) -> str:
        """Queue a shell request and return its msg_id, which is known before it is sent."""
        message: dict[str, Any] = self.client.session.msg(msg_type, content or {})
        self._queue.append(message)
        self._send_next()
        return str(message["header"]["msg_id"])

    def _send_next(self) -> None:
        if self._outstanding is None and self._queue:
            message = self._queue.popleft()
            self._outstanding = message["header"]["msg_id"]
            self.client.shell_channel.send(message)

    def _answered(self, msg_id: str) -> None:
        if msg_id == self._outstanding:
            self._outstanding = None
            self._send_next()

    def _drop_queue(self) -> None:
        """Forget what was waiting to be sent: the kernel it was for is gone."""
        self._queue.clear()
        self._outstanding = None

    def send_input(self, text: str) -> None:
        """Answer a pending :class:`~pystudio.messages.InputRequest`."""
        self.client.input(text)

    async def _await_reply(
        self, send: Callable[[], str], timeout: float | None = REQUEST_TIMEOUT
    ) -> dict[str, Any]:
        msg_id = send()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(msg_id, None)
            if not future.done() or future.cancelled():
                # Nobody is waiting any more, so do not send it if it has not gone.
                self._queue = deque(
                    message for message in self._queue if message["header"]["msg_id"] != msg_id
                )

    async def barrier(self, timeout: float = READY_TIMEOUT) -> None:
        """Return once the kernel has finished everything queued before this call.

        ipykernel serves shell requests in order, so a reply to a request sent
        now proves every earlier execution has completed. iopub is a separate
        socket, so a caller that needs the output as well should wait for the
        trailing ``idle`` after this returns.
        """
        await self._await_reply(lambda: self._request("kernel_info_request"), timeout=timeout)

    async def _wait_ready(self, timeout: float = READY_TIMEOUT) -> None:
        """Wait for the kernel to answer ``kernel_info_request``.

        ``KernelClient.wait_for_ready`` reads the shell channel itself, which
        would fight the pump for replies, so readiness is asked for through the
        same futures map as every other request. Requests sent before the kernel
        binds its sockets are simply dropped, hence the retry.
        """
        deadline = time.monotonic() + timeout
        while True:
            try:
                await self.barrier(timeout=2.0)
                return
            except TimeoutError:
                # The kernel never saw that request, so its answer is not coming.
                self._drop_queue()
                if time.monotonic() >= deadline:
                    raise

    async def _install_helper(self) -> None:
        await self.execute(SETUP, silent=True, store_history=False)

    # ----------------------------------------------------------------------- pumps

    async def _pump(
        self,
        receive: Callable[[], Any],
        handle: Callable[[dict[str, Any]], None],
    ) -> None:
        while True:
            try:
                message = await receive()
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._closing:
                    log.exception("channel pump stopped")
                return
            try:
                handle(message)
            except Exception:
                log.exception("failed to handle kernel message")

    async def _watch_alive(self) -> None:
        while True:
            await asyncio.sleep(ALIVE_POLL_SECONDS)
            if self._kc is None or self._restarting or self._closing:
                continue
            try:
                alive = await self._kc.is_alive()
            except asyncio.CancelledError:
                raise
            except Exception:
                return
            if not alive:
                self._fail_pending("the kernel died")
                self._emit(m.KernelStatus("dead"))
                return

    # -------------------------------------------------------------------- handlers

    def _handle_iopub(self, message: dict[str, Any]) -> None:
        msg_type = message["header"]["msg_type"]
        parent_id = self._parent_id(message)
        content: dict[str, Any] = message.get("content") or {}

        # Quiet requests must stay completely invisible. Letting a probe's
        # busy/idle churn through would retrigger the refresh it was sent for,
        # forever.
        if parent_id in self._quiet:
            return

        if msg_type == "status":
            state = content.get("execution_state", "")
            if state in ("idle", "busy", "starting"):
                self._emit(m.KernelStatus(state))
            return

        if parent_id in self._silent:
            return

        if msg_type == "execute_input":
            self._emit(
                m.ExecuteInput(
                    code=content.get("code", ""),
                    execution_count=int(content.get("execution_count") or 0),
                )
            )
        elif msg_type == "stream":
            self._emit(
                m.StreamOutput(name=content.get("name", "stdout"), text=content.get("text", ""))
            )
        elif msg_type == "execute_result":
            self._emit(
                m.ExecuteResult(
                    execution_count=int(content.get("execution_count") or 0),
                    data=content.get("data") or {},
                )
            )
        elif msg_type in ("display_data", "update_display_data"):
            transient: dict[str, Any] = content.get("transient") or {}
            self._emit(
                m.DisplayData(
                    data=content.get("data") or {},
                    display_id=transient.get("display_id"),
                    update=msg_type == "update_display_data",
                    metadata=content.get("metadata") or {},
                )
            )
        elif msg_type == "error":
            self._emit(
                m.KernelError(
                    ename=content.get("ename", ""),
                    evalue=content.get("evalue", ""),
                    traceback=list(content.get("traceback") or []),
                )
            )
        elif msg_type == "clear_output":
            self._emit(m.ClearOutput(wait=bool(content.get("wait"))))

    def _handle_shell(self, message: dict[str, Any]) -> None:
        parent_id = self._parent_id(message)
        content: dict[str, Any] = message.get("content") or {}
        self._answered(parent_id)

        # Awaited requests come first: a quiet expression is tracked like a
        # probe but its reply belongs to whoever is waiting for it.
        future = self._pending.get(parent_id)
        if future is not None and not future.done():
            future.set_result(content)
            return

        if parent_id in self._probes:
            self._emit_snapshot(content)

    def _handle_stdin(self, message: dict[str, Any]) -> None:
        if message["header"]["msg_type"] != "input_request":
            return
        content: dict[str, Any] = message.get("content") or {}
        self._emit(
            m.InputRequest(prompt=content.get("prompt", ""), password=bool(content.get("password")))
        )

    def _emit_snapshot(self, content: dict[str, Any]) -> None:
        result: dict[str, Any] = (content.get("user_expressions") or {}).get("vars") or {}
        if result.get("status") != "ok":
            return
        text = (result.get("data") or {}).get("text/plain")
        if not text:
            return
        self._emit(m.VariablesSnapshot(parse_probe(text)))

    # ------------------------------------------------------------------- internals

    def _fail_pending(self, reason: str) -> None:
        self._drop_queue()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(KernelReset(reason))

    @staticmethod
    def _track(store: dict[str, None], msg_id: str) -> None:
        store[msg_id] = None
        while len(store) > TRACKED_IDS:
            store.pop(next(iter(store)))

    @staticmethod
    def _parent_id(message: dict[str, Any]) -> str:
        parent: dict[str, Any] = message.get("parent_header") or {}
        return str(parent.get("msg_id", ""))

    def _emit(self, message: Message) -> None:
        try:
            self.sink(message)
        except Exception:
            log.exception("kernel message sink failed")
