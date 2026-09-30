"""Shared fixtures: a real kernel, and a recorder standing in for the app."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

import pytest
from textual.message import Message

from pystudio.kernel import KernelSession

T = TypeVar("T", bound=Message)

WAIT_TIMEOUT = 30.0


class Recorder:
    """Collects messages the way the app would, and waits for one to show up."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    def __call__(self, message: Message) -> None:
        self.messages.append(message)

    def clear(self) -> None:
        self.messages.clear()

    def of(self, kind: type[T]) -> list[T]:
        return [message for message in self.messages if isinstance(message, kind)]

    async def wait_for(
        self,
        kind: type[T],
        *,
        match: Callable[[T], bool] | None = None,
        timeout: float = WAIT_TIMEOUT,
    ) -> T:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for message in self.of(kind):
                if match is None or match(message):
                    return message
            await asyncio.sleep(0.02)
        seen = ", ".join(type(message).__name__ for message in self.messages) or "nothing"
        raise AssertionError(f"no {kind.__name__} within {timeout}s (saw: {seen})")

    async def settle(self, timeout: float = WAIT_TIMEOUT, quiet: float = 0.2) -> None:
        """Wait for idle and for the traffic to stop, then forget what was seen.

        Startup produces two idles, one for ``kernel_info`` and one for the
        silent setup cell, so waiting for the first would leave the second to
        land in a test that has already cleared the recorder.
        """
        from pystudio import messages as m

        await self.wait_for(m.KernelStatus, match=lambda s: s.state == "idle", timeout=timeout)
        deadline = time.monotonic() + timeout
        seen = len(self.messages)
        stable_until = time.monotonic() + quiet
        while time.monotonic() < deadline:
            await asyncio.sleep(0.02)
            if len(self.messages) != seen:
                seen = len(self.messages)
                stable_until = time.monotonic() + quiet
            elif time.monotonic() >= stable_until:
                break
        self.clear()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
async def kernel(recorder: Recorder, tmp_path) -> AsyncIterator[KernelSession]:
    session = KernelSession(recorder, cwd=tmp_path)
    await session.start()
    await recorder.settle()
    try:
        yield session
    finally:
        await session.shutdown()


class NvimHarness:
    """A real ``nvim --embed`` with a grid attached, for integration tests."""

    def __init__(
        self, *, argv: tuple[str, ...] = ("--clean", "-n"), cols: int = 80, rows: int = 24
    ):
        from pystudio.nvim import Grid, NvimRpc

        self.grid = Grid(cols, rows)
        self.notifications: list[tuple[str, list]] = []
        self.flushes = 0
        self.channel = 0
        self.rpc = NvimRpc(on_notification=self._on_notification, argv=argv)

    def _on_notification(self, method: str, params: list) -> None:
        if method == "redraw":
            # A redraw notification's params array *is* the list of events.
            if self.grid.handle_redraw(params):
                self.flushes += 1
            return
        self.notifications.append((method, params))

    async def start(self) -> None:
        await self.rpc.start()
        info = await self.rpc.request("nvim_get_api_info")
        self.channel = int(info[0])
        await self.rpc.request(
            "nvim_ui_attach",
            self.grid.width,
            self.grid.height,
            {"rgb": True, "ext_linegrid": True},
        )
        await self.wait_until(lambda: self.flushes > 0)

    async def close(self) -> None:
        await self.rpc.close()

    async def install_send_lua(self) -> None:
        from pystudio.nvim.bootstrap import load_lua

        await self.rpc.request("nvim_exec_lua", load_lua(), [self.channel])

    def sent(self) -> list[tuple[str, list]]:
        return [item for item in self.notifications if item[0].startswith("pystudio_")]

    async def wait_until(
        self,
        predicate: Callable[[], bool],
        *,
        timeout: float = 10.0,
        what: str = "condition",
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"{what} never became true within {timeout}s")


@pytest.fixture
async def nvim() -> AsyncIterator[NvimHarness]:
    harness = NvimHarness()
    await harness.start()
    try:
        yield harness
    finally:
        await harness.close()
