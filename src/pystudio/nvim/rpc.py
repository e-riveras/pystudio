"""msgpack-RPC over a ``nvim --embed`` process.

Three frame shapes travel on the wire:

==============  ===========================================
request         ``[0, msgid, method, params]``
response        ``[1, msgid, error, result]``
notification    ``[2, method, params]``
==============  ===========================================

Neovim may send requests of its own (``rpcrequest`` from Lua), and it blocks
until they are answered, so unhandled ones get an error reply rather than
silence.

This is deliberately not pynvim: its event loop is greenlet-based, and the app it
lives in is asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

import msgpack

log = logging.getLogger(__name__)

REQUEST = 0
RESPONSE = 1
NOTIFICATION = 2

READ_SIZE = 65536

NotificationHandler = Callable[[str, list[Any]], None]
RequestHandler = Callable[[str, list[Any]], Any]
ExitHandler = Callable[[int], None]


class NvimError(RuntimeError):
    """Neovim answered a request with an error."""


class NvimRpc:
    """A Neovim child process and the RPC plumbing around it."""

    def __init__(
        self,
        *,
        on_notification: NotificationHandler,
        on_exit: ExitHandler | None = None,
        on_request: RequestHandler | None = None,
        executable: str = "nvim",
        argv: Sequence[str] = (),
    ) -> None:
        self._on_notification = on_notification
        self._on_exit = on_exit
        self._on_request = on_request
        self._executable = executable
        self._argv = list(argv)
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 0
        self._closing = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Spawn Neovim. It waits for a UI to attach before finishing startup."""
        env = dict(os.environ)
        # Nested Neovim is legitimate here, but tools that key off $NVIM would
        # otherwise think they are inside a terminal buffer of a parent Neovim.
        env.pop("NVIM", None)
        env.pop("NVIM_LISTEN_ADDRESS", None)
        self._process = await asyncio.create_subprocess_exec(
            self._executable,
            "--embed",
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        self._reader = asyncio.create_task(self._read_loop(), name="nvim-read")

    async def close(self) -> None:
        """Ask Neovim to quit, then make sure the process and task are gone."""
        self._closing = True
        process = self._process
        if process is not None and process.returncode is None:
            with_timeout = self._try_quit(process)
            try:
                await asyncio.wait_for(with_timeout, timeout=2.0)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
            self._reader = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._process = None

    async def _try_quit(self, process: asyncio.subprocess.Process) -> None:
        try:
            self.notify("nvim_command", "qall!")
        except Exception:
            process.terminate()
        await process.wait()

    # ------------------------------------------------------------------- messages

    async def request(self, method: str, *params: Any, timeout: float | None = 10.0) -> Any:
        """Call ``method`` and wait for its reply."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("nvim is not started")
        self._next_id += 1
        msgid = self._next_id
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[msgid] = future
        self._write([REQUEST, msgid, method, list(params)])
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(msgid, None)

    def notify(self, method: str, *params: Any) -> None:
        """Call ``method`` and do not wait. Used for keys, where latency matters."""
        self._write([NOTIFICATION, method, list(params)])

    def _write(self, frame: list[Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("nvim is not started")
        self._process.stdin.write(msgpack.packb(frame, use_bin_type=True))

    # ---------------------------------------------------------------------- reader

    async def _read_loop(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        while True:
            try:
                data = await process.stdout.read(READ_SIZE)
            except asyncio.CancelledError:
                raise
            except Exception:
                break
            if not data:
                break
            unpacker.feed(data)
            for frame in unpacker:
                try:
                    self._dispatch(frame)
                except Exception:
                    log.exception("failed to handle nvim frame")
        await self._handle_eof()

    async def _handle_eof(self) -> None:
        process = self._process
        returncode = 0
        if process is not None:
            returncode = await process.wait()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(NvimError("nvim exited"))
        self._pending.clear()
        if self._on_exit is not None and not self._closing:
            self._on_exit(returncode)

    def _dispatch(self, frame: Any) -> None:
        if not isinstance(frame, list) or not frame:
            return
        kind = frame[0]
        if kind == RESPONSE:
            _, msgid, error, result = frame
            future = self._pending.get(msgid)
            if future is None or future.done():
                return
            if error is not None:
                future.set_exception(NvimError(self._describe(error)))
            else:
                future.set_result(result)
        elif kind == NOTIFICATION:
            _, method, params = frame
            self._on_notification(method, list(params))
        elif kind == REQUEST:
            _, msgid, method, params = frame
            self._answer(msgid, method, list(params))

    def _answer(self, msgid: int, method: str, params: list[Any]) -> None:
        if self._on_request is None:
            self._write([RESPONSE, msgid, f"pystudio: unhandled request {method!r}", None])
            return
        try:
            result = self._on_request(method, params)
        except Exception as error:  # noqa: BLE001 - the reply must go out regardless
            self._write([RESPONSE, msgid, str(error), None])
            return
        self._write([RESPONSE, msgid, None, result])

    @staticmethod
    def _describe(error: Any) -> str:
        if isinstance(error, list) and len(error) == 2:
            return str(error[1])
        return str(error)
