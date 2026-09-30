"""The variable explorer: whatever the kernel says is in the namespace."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from textual.message import Message
from textual.widgets import DataTable

from pystudio.introspect import Variable

COLUMNS = ("name", "type", "shape", "value")


class VariablesPane(DataTable):
    """A table rebuilt from each snapshot, keeping the user's place."""

    BINDINGS = [("enter", "inspect", "show value")]

    @dataclass
    class Inspect(Message):
        """The user asked to see one variable."""

        variable: Variable

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._variables: dict[str, Variable] = {}

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns(*COLUMNS)

    def show(self, variables: list[Variable]) -> None:
        """Replace every row, restoring the selected name and scroll position."""
        self._variables = {variable.name: variable for variable in variables}
        selected = self.selected_name
        offset = self.scroll_offset.y
        self.clear()
        for variable in variables:
            self.add_row(
                variable.name,
                variable.type,
                variable.shape,
                variable.preview,
                key=variable.name,
            )
        if selected is not None:
            with contextlib.suppress(Exception):
                self.move_cursor(row=self.get_row_index(selected))
        self.scroll_to(y=offset, animate=False)

    @property
    def selected_name(self) -> str | None:
        """The name under the cursor, or None when the table is empty."""
        if not self.row_count:
            return None
        with contextlib.suppress(Exception):
            key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
            if key.value is not None:
                return str(key.value)
        return None

    def action_inspect(self) -> None:
        name = self.selected_name
        variable = self._variables.get(name) if name is not None else None
        if variable is not None:
            self.post_message(self.Inspect(variable))
