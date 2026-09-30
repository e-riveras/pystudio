"""A scrollable view of a DataFrame, Series or array, the way RStudio's View() is.

Pages are fetched from the kernel on demand, so opening a million-row frame costs
one page. Sorting is done in the kernel too: sorting only the loaded page would
be a lie about the data.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from pystudio.introspect import Frame, Variable

PAGE = 200
"""Rows per fetch."""

PREFETCH = 20
"""Fetch the next page once the cursor comes this close to the end."""

Fetch = Callable[..., Awaitable[Frame]]

INDEX_KEY = "__index__"


class FrameViewer(ModalScreen[None]):
    """Modal table over one variable. Escape closes it."""

    BINDINGS = [
        Binding("escape,q", "dismiss", "close"),
        Binding("s", "sort", "sort by column"),
    ]

    DEFAULT_CSS = """
    FrameViewer {
        align: center middle;
        background: $background 60%;
    }
    FrameViewer > #frame-box {
        width: 90%;
        height: 90%;
        border: round $accent;
        border-title-color: $accent;
        border-title-align: left;
        background: $surface;
    }
    FrameViewer #frame-table {
        height: 1fr;
    }
    FrameViewer #frame-caption {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, variable: Variable, fetch: Fetch) -> None:
        super().__init__()
        self.variable = variable
        self._fetch = fetch
        self._loaded = 0
        self._total = 0
        self._columns_total = 0
        self._sort: str | None = None
        self._ascending = True
        self._loading = False

    def compose(self):
        with Vertical(id="frame-box"):
            yield DataTable(id="frame-table")
            yield Static("loading…", id="frame-caption")

    def on_mount(self) -> None:
        table = self.table
        table.cursor_type = "cell"
        table.zebra_stripes = True
        table.fixed_columns = 1
        self.query_one(
            "#frame-box"
        ).border_title = f"{self.variable.name}  {self.variable.type} {self.variable.shape}".strip()
        self.run_worker(self.load(reset=True), name="frame")

    @property
    def table(self) -> DataTable:
        return self.query_one("#frame-table", DataTable)

    @property
    def caption(self) -> Static:
        return self.query_one("#frame-caption", Static)

    # ------------------------------------------------------------------- fetching

    async def load(self, *, reset: bool = False) -> None:
        """Fetch one page, appending it or starting the table over."""
        if self._loading:
            return
        self._loading = True
        try:
            start = 0 if reset else self._loaded
            frame = await self._fetch(
                self.variable.name,
                start,
                start + PAGE,
                sort=self._sort,
                ascending=self._ascending,
            )
            if not frame.viewable:
                self.caption.update(
                    "not viewable" if frame.kind == "other" else "the variable is gone"
                )
                return

            table = self.table
            # Rebuilding the table resets the cursor, which would otherwise land
            # back on the index column and make a second sort a no-op.
            column = table.cursor_coordinate.column if reset else None
            if reset:
                table.clear(columns=True)
                table.add_column("", key=INDEX_KEY)
                for position, name in enumerate(frame.columns):
                    # Duplicate column names are legal in a DataFrame, so keys
                    # are positional rather than the label.
                    table.add_column(name, key=f"c{position}")
                self._loaded = 0

            for offset, row in enumerate(frame.rows):
                label = frame.index[offset] if offset < len(frame.index) else ""
                table.add_row(label, *row)
            self._loaded += len(frame.rows)
            self._total = frame.rows_total
            self._columns_total = frame.columns_total
            if column is not None and table.row_count:
                table.move_cursor(row=0, column=min(column, len(table.columns) - 1))
            self._describe()
        finally:
            self._loading = False

    def _describe(self) -> None:
        parts = [f"{self._loaded} of {self._total} rows", f"{self._columns_total} columns"]
        if self._columns_total > len(self.table.columns) - 1:
            parts.append(f"first {len(self.table.columns) - 1} shown")
        if self._sort:
            parts.append(f"sorted by {self._sort} {'↑' if self._ascending else '↓'}")
        parts.append("s sorts · escape closes")
        self.caption.update(" · ".join(parts))

    # -------------------------------------------------------------------- paging

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if self._loaded < self._total and event.coordinate.row >= self._loaded - PREFETCH:
            self.run_worker(self.load(), name="frame-more")

    # ------------------------------------------------------------------- sorting

    def action_sort(self) -> None:
        self._sort_by(self.table.cursor_coordinate.column)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        self._sort_by(event.column_index)

    def _sort_by(self, column_index: int) -> None:
        columns = self.table.ordered_columns
        if not 0 < column_index < len(columns):
            return  # column 0 is the index
        label = str(columns[column_index].label)
        if self._sort == label:
            self._ascending = not self._ascending
        else:
            self._sort, self._ascending = label, True
        self.run_worker(self.load(reset=True), name="frame-sort")
