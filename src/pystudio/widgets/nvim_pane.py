"""A real Neovim, attached as a UI and painted into one Textual widget."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from textual import events
from textual.strip import Strip
from textual.widget import Widget

from pystudio import messages as m
from pystudio.nvim.bootstrap import load_all
from pystudio.nvim.grid import Grid
from pystudio.nvim.keys import key_event_to_nvim, mouse_button, mouse_modifiers
from pystudio.nvim.rpc import NvimRpc

log = logging.getLogger(__name__)

UI_OPTIONS = {"rgb": True, "ext_linegrid": True}
"""Only ext_linegrid: Neovim then draws the cmdline, popupmenu, messages and
tabline as ordinary cells, so this widget needs no special case for any of them."""


class NvimPane(Widget, can_focus=True):
    """Owns the Neovim process, its grid, and the input going into it."""

    def __init__(
        self,
        *,
        executable: str = "nvim",
        file: Path | str | None = None,
        clean: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        argv: list[str] = []
        if clean:
            argv.append("--clean")
        argv.append("-n")  # no swapfile: the editor is short-lived by design
        if file is not None:
            argv.append(str(file))
        self.grid = Grid(80, 24)
        self.channel = 0
        self._attached = False
        self.rpc = NvimRpc(
            on_notification=self._on_notification,
            on_exit=self._on_exit,
            executable=executable,
            argv=argv,
        )

    # ------------------------------------------------------------------ lifecycle

    async def on_mount(self) -> None:
        await self.rpc.start()
        info = await self.rpc.request("nvim_get_api_info")
        self.channel = int(info[0])
        await self._attach_ui()

    async def on_unmount(self) -> None:
        await self.rpc.close()

    async def _attach_ui(self) -> None:
        columns = max(self.size.width, 1)
        rows = max(self.size.height, 1)
        self.grid.resize(columns, rows)
        await self.rpc.request("nvim_ui_attach", columns, rows, UI_OPTIONS)
        self._attached = True
        for name, source in load_all():
            try:
                await self.rpc.request("nvim_exec_lua", source, [self.channel])
            except Exception:
                log.exception("failed to install %s", name)
        # The file on the command line is opened before the autocmd exists, so
        # the first buffer name is asked for rather than waited for.
        name = await self.rpc.request("nvim_buf_get_name", 0)
        if name:
            self.post_message(m.NvimEvent("pystudio_buffer", [str(name)]))
        # A resize can land while the attach is still in flight, and Neovim
        # clamps its grid to 12 columns, so the size is reconciled here.
        await self._sync_size()

    async def on_resize(self, event: events.Resize) -> None:
        # The event carries the outer size, borders included, so the content
        # size is read from the widget instead.
        await self._sync_size()

    async def _sync_size(self) -> None:
        if not self._attached or not self.rpc.running:
            return
        columns = max(self.size.width, 1)
        rows = max(self.size.height, 1)
        if (columns, rows) == (self.grid.width, self.grid.height):
            return
        # Neovim answers with grid_resize and a repaint; never resize locally.
        await self.rpc.request("nvim_ui_try_resize", columns, rows)

    # -------------------------------------------------------------------- incoming

    def _on_notification(self, method: str, params: list[Any]) -> None:
        if method == "redraw":
            # A redraw notification's params array *is* the list of events.
            if self.grid.handle_redraw(params):
                self.post_message(m.NvimRedraw())
            return
        if method == "pystudio_send":
            lines = params[0] if params else []
            self.post_message(m.NvimSendRequest([str(line) for line in lines]))
            return
        self.post_message(m.NvimEvent(method, list(params)))

    def _on_exit(self, returncode: int) -> None:
        self.post_message(m.NvimExited(returncode))

    def on_nvim_redraw(self, message: m.NvimRedraw) -> None:
        message.stop()
        self.refresh()

    # --------------------------------------------------------------------- painting

    def render_line(self, y: int) -> Strip:
        cursor = None
        if self.has_focus and y == self.grid.cursor_row:
            cursor = self.grid.cursor_col
        segments = self.grid.row_segments(y, cursor=cursor)
        strip = Strip(segments)
        return strip.adjust_cell_length(self.size.width, self.grid.style_for(0))

    # ------------------------------------------------------------------------ input

    async def on_key(self, event: events.Key) -> None:
        # Neovim owns its whole keyspace, so nothing here is left to bubble.
        event.stop()
        event.prevent_default()
        self.app.cancel_chord()
        keys = key_event_to_nvim(event)
        if keys and self.rpc.running:
            self.rpc.notify("nvim_input", keys)

    async def on_paste(self, event: events.Paste) -> None:
        event.stop()
        event.prevent_default()
        if self.rpc.running:
            # One atomic undo block, and far cheaper than per-key input.
            self.rpc.notify("nvim_paste", event.text, True, -1)

    def _mouse(self, event: events.MouseEvent, button: str, action: str) -> None:
        if not self.rpc.running or not self.grid.mouse_enabled:
            return
        self.rpc.notify(
            "nvim_input_mouse",
            button,
            action,
            mouse_modifiers(event),
            0,
            event.offset.y,
            event.offset.x,
        )

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.focus()
        button = mouse_button(event)
        if button:
            self._mouse(event, button, "press")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        button = mouse_button(event)
        if button:
            self._mouse(event, button, "release")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if mouse_button(event):
            self._mouse(event, "left", "drag")

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self._mouse(event, "wheel", "down")

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._mouse(event, "wheel", "up")

    def on_focus(self) -> None:
        if self.rpc.running:
            self.rpc.notify("nvim_ui_set_focus", True)
        self.refresh()

    def on_blur(self) -> None:
        if self.rpc.running:
            self.rpc.notify("nvim_ui_set_focus", False)
        self.refresh()

    # ---------------------------------------------------------------- app requests

    def publish_kernel_state(self, state: str) -> None:
        """Expose the kernel state as ``g:pystudio_kernel`` for statuslines."""
        if self.rpc.running:
            self.rpc.notify("nvim_set_var", "pystudio_kernel", state)

    async def request_quit(self) -> None:
        """Let Neovim prompt about unsaved buffers, rather than doing it here."""
        if self.rpc.running:
            self.rpc.notify("nvim_command", "confirm qall")
