"""The screen Neovim paints into, as plain data.

Only ``ext_linegrid`` is requested from Neovim, which means the command line, the
completion popup, messages and the tabline are drawn as ordinary cells. That is
the point: this model stays a rectangle of characters, and no special case is
needed for any of those.

Nothing here imports Textual, so the whole redraw protocol can be tested by
feeding recorded event batches in.
"""

from __future__ import annotations

from typing import Any

from rich.segment import Segment
from rich.style import Style

DEFAULT_FG = 0xD0D0D0
DEFAULT_BG = 0x000000
DEFAULT_SP = 0xFF0000

UNDERLINE_ATTRS = ("underline", "undercurl", "underdotted", "underdashed")

BAR = "\u258f"
"""Left one-eighth block, the closest a character cell gets to a bar cursor."""


class Grid:
    """Cells, styles, cursor and mode, driven by ``redraw`` events."""

    def __init__(self, width: int = 80, height: int = 24) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self.text: list[list[str]] = []
        self.hl: list[list[int]] = []
        self.cursor_row = 0
        self.cursor_col = 0
        self.mode = "normal"
        self.mode_index = 0
        self.mode_infos: list[dict[str, Any]] = []
        self.cursor_style_enabled = False
        self.mouse_enabled = False
        self.title = ""
        self.default_fg = DEFAULT_FG
        self.default_bg = DEFAULT_BG
        self.default_sp = DEFAULT_SP
        self._attrs: dict[int, dict[str, Any]] = {}
        self._styles: dict[int, Style] = {}
        self._blank()

    # -------------------------------------------------------------------- geometry

    def _blank(self) -> None:
        self.text = [[" "] * self.width for _ in range(self.height)]
        self.hl = [[0] * self.width for _ in range(self.height)]

    def resize(self, width: int, height: int) -> None:
        """Resize the cell matrix, keeping whatever overlaps."""
        width, height = max(1, width), max(1, height)
        text = [[" "] * width for _ in range(height)]
        hl = [[0] * width for _ in range(height)]
        for y in range(min(height, self.height)):
            columns = min(width, self.width)
            text[y][:columns] = self.text[y][:columns]
            hl[y][:columns] = self.hl[y][:columns]
        self.width, self.height = width, height
        self.text, self.hl = text, hl
        self.cursor_row = min(self.cursor_row, height - 1)
        self.cursor_col = min(self.cursor_col, width - 1)

    # --------------------------------------------------------------------- styling

    def _color(self, value: int | None) -> str | None:
        return None if value is None else f"#{value:06x}"

    def style_for(self, hl_id: int) -> Style:
        """The Rich style for a highlight id, built once and cached."""
        cached = self._styles.get(hl_id)
        if cached is not None:
            return cached
        attrs = self._attrs.get(hl_id, {})
        foreground = attrs.get("foreground")
        background = attrs.get("background")
        if attrs.get("reverse"):
            foreground, background = (
                background if background is not None else self.default_bg,
                foreground if foreground is not None else self.default_fg,
            )
        style = Style(
            color=self._color(foreground if foreground is not None else self.default_fg),
            bgcolor=self._color(background if background is not None else self.default_bg),
            bold=bool(attrs.get("bold")) or None,
            italic=bool(attrs.get("italic")) or None,
            strike=bool(attrs.get("strikethrough")) or None,
            # Rich has no undercurl, so the dotted and dashed variants collapse
            # onto a plain underline and underdouble keeps its own attribute.
            underline=any(attrs.get(name) for name in UNDERLINE_ATTRS) or None,
            underline2=bool(attrs.get("underdouble")) or None,
        )
        self._styles[hl_id] = style
        return style

    # -------------------------------------------------------------------- redrawing

    def handle_redraw(self, events: list[Any]) -> bool:
        """Apply a ``redraw`` batch. True if Neovim asked for a repaint."""
        flushed = False
        for event in events:
            if not event:
                continue
            name, *calls = event
            if name == "flush":
                flushed = True
                continue
            handler = getattr(self, f"_ev_{name}", None)
            if handler is None:
                continue
            if not calls:
                handler()
                continue
            for args in calls:
                handler(*args)
        return flushed

    # Each handler mirrors one event from |ui-linegrid|. Without ext_multigrid
    # there is only ever grid 1, so the grid argument is accepted and ignored.

    def _ev_grid_resize(self, _grid: int, width: int, height: int) -> None:
        self.resize(width, height)

    def _ev_grid_clear(self, _grid: int = 1) -> None:
        self._blank()

    def _ev_grid_destroy(self, _grid: int = 1) -> None:
        self._blank()

    def _ev_grid_cursor_goto(self, _grid: int, row: int, col: int) -> None:
        self.cursor_row = max(0, min(row, self.height - 1))
        self.cursor_col = max(0, min(col, self.width - 1))

    def _ev_grid_line(
        self,
        _grid: int,
        row: int,
        col_start: int,
        cells: list[list[Any]],
        _wrap: bool = False,
    ) -> None:
        if not 0 <= row < self.height:
            return
        text_row, hl_row = self.text[row], self.hl[row]
        hl_id = 0
        col = col_start
        for cell in cells:
            char = cell[0]
            if len(cell) >= 2:
                hl_id = int(cell[1])
            repeat = int(cell[2]) if len(cell) >= 3 else 1
            for _ in range(repeat):
                if col >= self.width:
                    return
                text_row[col] = char
                hl_row[col] = hl_id
                col += 1

    def _ev_grid_scroll(
        self,
        _grid: int,
        top: int,
        bot: int,
        left: int,
        right: int,
        rows: int,
        _cols: int = 0,
    ) -> None:
        if rows == 0:
            return
        # Positive rows scroll content up, negative down. Iterate so that a
        # destination row is written only after its source row has been read.
        destinations = range(top, bot - rows) if rows > 0 else range(bot - 1, top - rows - 1, -1)
        for destination in destinations:
            source = destination + rows
            if not (0 <= source < self.height and 0 <= destination < self.height):
                continue
            self.text[destination][left:right] = self.text[source][left:right]
            self.hl[destination][left:right] = self.hl[source][left:right]

    def _ev_hl_attr_define(
        self,
        hl_id: int,
        rgb_attrs: dict[str, Any],
        _cterm_attrs: dict[str, Any] | None = None,
        _info: list[Any] | None = None,
    ) -> None:
        self._attrs[int(hl_id)] = dict(rgb_attrs)
        self._styles.pop(int(hl_id), None)

    def _ev_default_colors_set(
        self,
        rgb_fg: int,
        rgb_bg: int,
        rgb_sp: int,
        _cterm_fg: int = 0,
        _cterm_bg: int = 0,
    ) -> None:
        if rgb_fg >= 0:
            self.default_fg = rgb_fg
        if rgb_bg >= 0:
            self.default_bg = rgb_bg
        if rgb_sp >= 0:
            self.default_sp = rgb_sp
        # Styles resolve `reverse` against the defaults, so they all go stale.
        self._styles.clear()

    def _ev_mode_info_set(
        self, cursor_style_enabled: bool, mode_info: list[dict[str, Any]]
    ) -> None:
        self.cursor_style_enabled = bool(cursor_style_enabled)
        self.mode_infos = list(mode_info)

    def _ev_mode_change(self, mode: str, mode_index: int) -> None:
        self.mode = mode
        self.mode_index = int(mode_index)

    def _ev_mouse_on(self) -> None:
        self.mouse_enabled = True

    def _ev_mouse_off(self) -> None:
        self.mouse_enabled = False

    def _ev_set_title(self, title: str) -> None:
        self.title = title

    # --------------------------------------------------------------------- reading

    @property
    def mode_info(self) -> dict[str, Any]:
        if 0 <= self.mode_index < len(self.mode_infos):
            return self.mode_infos[self.mode_index]
        return {}

    @property
    def cursor_shape(self) -> str:
        """``block``, ``horizontal`` or ``vertical`` for the current mode."""
        if not self.cursor_style_enabled:
            return "block"
        return str(self.mode_info.get("cursor_shape", "block"))

    @property
    def cursor_attr_id(self) -> int:
        """Highlight Neovim wants the cursor drawn with, 0 when it has none."""
        return int(self.mode_info.get("attr_id") or 0)

    def cursor_segment(self, char: str, hl_id: int) -> Segment:
        """The cursor cell, drawn according to the shape of the current mode.

        A cell cannot be subdivided, so a vertical cursor becomes a thin bar
        glyph in place of the character, and a horizontal one underlines the
        character instead of covering it.
        """
        attr_id = self.cursor_attr_id
        if attr_id:
            cursor_style = self.style_for(attr_id)
        else:
            cursor_style = self.style_for(hl_id) + Style(reverse=True)

        shape = self.cursor_shape
        if shape == "vertical":
            color = cursor_style.bgcolor or cursor_style.color
            return Segment(BAR, Style(color=color, bgcolor=self._color(self.default_bg)))
        if shape == "horizontal":
            return Segment(char, self.style_for(hl_id) + Style(underline=True))
        return Segment(char, cursor_style)

    def row_text(self, y: int) -> str:
        """Row ``y`` as a string. Useful in tests and for the status bar."""
        if not 0 <= y < self.height:
            return ""
        return "".join(char or "" for char in self.text[y])

    def row_segments(self, y: int, cursor: int | None = None) -> list[Segment]:
        """Row ``y`` as Rich segments, runs of one highlight coalesced.

        A double-width character arrives as the character followed by an empty
        cell; the empty cell is dropped, since the character already covers both
        columns on screen.
        """
        if not 0 <= y < self.height:
            return []
        text_row, hl_row = self.text[y], self.hl[y]
        segments: list[Segment] = []
        run: list[str] = []
        run_hl = hl_row[0] if self.width else 0

        def flush_run() -> None:
            if run:
                segments.append(Segment("".join(run), self.style_for(run_hl)))
                run.clear()

        for x in range(self.width):
            char = text_row[x]
            if char == "":
                continue
            hl_id = hl_row[x]
            if x == cursor:
                flush_run()
                segments.append(self.cursor_segment(char, hl_id))
                run_hl = hl_id
                continue
            if hl_id != run_hl:
                flush_run()
                run_hl = hl_id
            run.append(char)
        flush_run()
        return segments
