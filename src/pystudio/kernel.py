"""The kernel layer: one Jupyter kernel, shared by the editor and the console.

``KernelSession`` owns an out-of-process kernel and one asyncio task per ZMQ
channel. Each task translates wire messages into :mod:`pystudio.messages`
objects and hands them to a sink callback. Nothing here imports a widget, so the
whole layer is testable without a UI.

The shell channel has exactly one consumer, this class. Request/reply pairs that
callers need to await (completion, inspection) are resolved through a futures
map keyed by ``msg_id``, rather than by reading the channel a second time, which
would let two consumers steal each other's replies.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jupyter_client.asynchronous.client import AsyncKernelClient
from jupyter_client.manager import AsyncKernelManager
from textual.message import Message

from pystudio import messages as m
from pystudio.introspect import (
    PROBE_EXPR,
    SETUP,
    Frame,
    frame_expr,
    parse_frame,
    parse_probe,
)

log = logging.getLogger(__name__)

Sink = Callable[[Message], None]

READY_TIMEOUT = 60.0
REQUEST_TIMEOUT = 5.0
FRAME_TIMEOUT = 15.0
ALIVE_POLL_SECONDS = 2.0
TRACKED_IDS = 16
"""How many recent silent executions, quiet requests and probes stay tracked.

Shell replies and iopub messages travel on different channels, so a reply can
arrive before the ``idle`` status that belongs to the same request. Ids are
therefore forgotten by age rather than on reply, or that late status would leak
into the UI and retrigger the refresh it came from.
"""


class KernelSession:
    """A running kernel plus the tasks that pump its channels."""

    def __init__(
        self,
        sink: Sink,
        *,
        kernel_name: str = "python3",
        cwd: Path | str | None = None,
    ) -> None:
        self.kernel_name = kernel_name
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.sink = sink
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

    # ------------------------------------------------------------------ lifecycle

    @property
    def client(self) -> AsyncKernelClient:
        if self._kc is None:
            raise RuntimeError("kernel is not started")
        return self._kc

    async def start(self) -> None:
        """Launch the kernel, connect, and install the introspection helper."""
        self._emit(m.KernelStatus("starting"))
        km = AsyncKernelManager(kernel_name=self.kernel_name)
        await km.start_kernel(cwd=str(self.cwd))
        kc = km.client()
        kc.start_channels()
        await kc.wait_for_ready(timeout=READY_TIMEOUT)
        self._km, self._kc = km, kc

        self._tasks = [
            asyncio.create_task(self._pump(kc.get_iopub_msg, self._handle_iopub), name="iopub"),
            asyncio.create_task(self._pump(kc.get_shell_msg, self._handle_shell), name="shell"),
            asyncio.create_task(self._pump(kc.get_stdin_msg, self._handle_stdin), name="stdin"),
            asyncio.create_task(self._watch_alive(), name="alive"),
        ]
        await self._install_helper()

    async def shutdown(self) -> None:
        """Stop the pumps, the channels, and the kernel process."""
        self._closing = True
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

    async def restart(self) -> None:
        """Restart the kernel in place, keeping the same ports and channels."""
        if self._km is None:
            raise RuntimeError("kernel is not started")
        self._restarting = True
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
        if self._km is None:
            raise RuntimeError("kernel is not started")
        await self._km.interrupt_kernel()

    # -------------------------------------------------------------------- requests

    async def execute(
        self,
        code: str,
        *,
        silent: bool = False,
        store_history: bool = True,
    ) -> str:
        """Run ``code``. Output arrives later as messages. Returns the msg_id."""
        msg_id: str = self.client.execute(code, silent=silent, store_history=store_history)
        if silent:
            self._track(self._silent, msg_id)
        return msg_id

    async def probe_variables(self) -> str:
        """Take a variable snapshot without touching history or producing output."""
        msg_id: str = self.client.execute(
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
        content = await self._await_reply(
            lambda: self._send_expression(expression), timeout=FRAME_TIMEOUT
        )
        result: dict[str, Any] = (content.get("user_expressions") or {}).get("value") or {}
        if result.get("status") != "ok":
            return Frame(kind="other")
        text = (result.get("data") or {}).get("text/plain")
        return parse_frame(text) if text else Frame(kind="other")

    def _send_expression(self, expression: str) -> str:
        """Evaluate an expression quietly and return the request's msg_id."""
        msg_id: str = self.client.execute(
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
        return await self._await_reply(lambda: self.client.complete(code, cursor_pos))

    async def inspect(
        self, code: str, cursor_pos: int | None = None, detail_level: int = 0
    ) -> dict[str, Any]:
        """Ask the kernel for documentation at ``cursor_pos``."""
        return await self._await_reply(
            lambda: self.client.inspect(code, cursor_pos, detail_level=detail_level)
        )

    def send_input(self, text: str) -> None:
        """Answer a pending :class:`~pystudio.messages.InputRequest`."""
        self.client.input(text)

    async def _await_reply(
        self, send: Callable[[], str], timeout: float = REQUEST_TIMEOUT
    ) -> dict[str, Any]:
        msg_id = send()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(msg_id, None)

    async def barrier(self, timeout: float = READY_TIMEOUT) -> None:
        """Return once the kernel has finished everything queued before this call.

        ipykernel serves shell requests in order, so a reply to a request sent
        now proves every earlier execution has completed. iopub is a separate
        socket, so a caller that needs the output as well should wait for the
        trailing ``idle`` after this returns.
        """
        await self._await_reply(lambda: self.client.kernel_info(), timeout=timeout)

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
            if self._km is None or self._restarting or self._closing:
                continue
            try:
                alive = await self._km.is_alive()
            except asyncio.CancelledError:
                raise
            except Exception:
                return
            if not alive:
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
