"""The two columns of panes, and how the room is shared between them."""

from __future__ import annotations

from textual import events
from textual.containers import Horizontal
from textual.widget import Widget

STEP = 0.05
"""How far one key press moves a divider, as a share of the room."""

LOW, HIGH = 0.15, 0.85
"""No pane is squeezed below this share, or grown past it."""

DEFAULT = {"columns": 2 / 3, "left": 0.5, "right": 0.5}
"""The left column's share of the width, and the top pane's share of each column."""

PRESETS = {
    "default": (2 / 3, True),
    "wide plots": (0.5, True),
    "plots only": (0.5, False),
}
"""For each layout: the left column's share, and whether the top right pane shows."""


class Panes(Horizontal):
    """Two columns, ``#left`` and ``#right``, each with a top and a bottom pane.

    The dividers move by key, through :meth:`nudge`, and by dragging the border
    between two panes.
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.split = dict(DEFAULT)
        self.preset = "default"
        self._dragging: str | None = None

    def on_mount(self) -> None:
        self._apply()

    def _column(self, name: str) -> Widget:
        return self.query_one(f"#{name}")

    def _apply(self) -> None:
        left = round(self.split["columns"] * 1000)
        self._column("left").styles.width = f"{left}fr"
        self._column("right").styles.width = f"{1000 - left}fr"
        for name in ("left", "right"):
            top, bottom = self._ends(name)
            share = round(self.split[name] * 1000)
            top.styles.height = f"{share}fr"
            bottom.styles.height = f"{1000 - share}fr"

    def _ends(self, name: str) -> tuple[Widget, Widget]:
        children = self._column(name).children
        return children[0], children[-1]

    def set_split(self, which: str, share: float) -> None:
        """Put a divider at ``share`` of the room, within the limits."""
        self.split[which] = max(LOW, min(share, HIGH))
        self._apply()

    def nudge(self, which: str, steps: int) -> None:
        """Move the ``columns`` divider right, or a column's divider down, by ``steps``."""
        self.set_split(which, self.split[which] + steps * STEP)

    def place(self, widget: Widget | None) -> tuple[str, bool]:
        """The column ``widget`` is in, and whether it is in that column's top pane."""
        for name in ("left", "right"):
            top, _ = self._ends(name)
            if widget is not None and self._column(name) in widget.ancestors_with_self:
                return name, top in widget.ancestors_with_self
        return "left", True

    def cycle(self) -> str:
        """Move to the next preset layout and return its name."""
        names = list(PRESETS)
        self.preset = names[(names.index(self.preset) + 1) % len(names)]
        columns, top_right = PRESETS[self.preset]
        self._ends("right")[0].display = top_right
        self.split["right"] = DEFAULT["right"]
        self.set_split("columns", columns)
        return self.preset

    # ------------------------------------------------------------------------ mouse

    def _grip(self, x: int, y: int) -> str | None:
        """The divider under a screen position, if there is one.

        A divider is the pair of borders where two panes meet.
        """
        edge = self._column("right").region.x
        if x in (edge - 1, edge):
            return "columns"
        for name in ("left", "right"):
            top, bottom = self._ends(name)
            if not (top.display and bottom.display):
                continue
            if self._column(name).region.contains(x, y) and y in (
                bottom.region.y - 1,
                bottom.region.y,
            ):
                return name
        return None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        grip = self._grip(event.screen_x, event.screen_y)
        if grip is not None:
            event.stop()
            self._dragging = grip
            self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging is None:
            return
        if self._dragging == "columns":
            region = self.region
            if region.width:
                self.set_split("columns", (event.screen_x - region.x) / region.width)
            return
        region = self._column(self._dragging).region
        if region.height:
            self.set_split(self._dragging, (event.screen_y - region.y) / region.height)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging is not None:
            self._dragging = None
            self.release_mouse()
