"""Looking inside the kernel without making a mess of the console.

``SETUP`` is run once, silently, when a kernel comes up. It defines helpers in
the user namespace: one that describes every interesting name, one that
describes a slice of a table-like object, and a few that keep matplotlib
figures alive so the plot pane can have them drawn again at another size.

They are read through an ``execute_request`` that has empty ``code`` and asks for
the call in ``user_expressions``. The answer rides back on the ``execute_reply``,
so nothing is added to the kernel's history and nothing is published on iopub for
the console to display.
"""

from __future__ import annotations

import ast
import base64
import contextlib
import json
from dataclasses import dataclass, field

PROBE_EXPR = "__pystudio_inspect__()"
"""Expression to pass in ``user_expressions`` to take a variable snapshot."""

PREVIEW_CHARS = 60
"""How much of a value's repr reaches the variable explorer."""

CELL_CHARS = 40
"""How much of a value reaches one cell of the table viewer."""

MAX_COLUMNS = 50
"""Columns beyond this are not sent; the viewer says how many exist."""

MAX_FIGURES = 20
"""How many figures the kernel keeps alive so the plot pane can draw them again."""

_SETUP_TEMPLATE = '''
try:
    get_ipython().run_line_magic("matplotlib", "inline")
except Exception:
    pass


def __pystudio_shorten__(value, limit):
    """Collapse whitespace and truncate. Defined by pystudio."""
    try:
        text = " ".join(repr(value).split())
    except Exception:
        return "<repr failed>"
    if len(text) > limit:
        text = text[: limit - 1] + "\\u2026"
    return text


def __pystudio_inspect__():
    """Describe the user namespace as a JSON string. Defined by pystudio."""
    import json as _json
    import types as _types

    _hidden = {"In", "Out", "get_ipython", "exit", "quit", "open"}
    _ns = get_ipython().user_ns
    _rows = []
    for _name in sorted(_ns):
        if _name.startswith("_") or _name in _hidden:
            continue
        _value = _ns[_name]
        if isinstance(_value, _types.ModuleType):
            continue

        _shape = ""
        _dims = getattr(_value, "shape", None)
        if isinstance(_dims, tuple):
            # A zero-dimensional array is a scalar; an empty shape says nothing.
            _shape = str(tuple(int(_d) for _d in _dims)) if _dims else ""
        else:
            try:
                _shape = str(len(_value))
            except Exception:
                _shape = ""

        _rows.append(
            {
                "name": _name,
                "type": type(_value).__name__,
                "shape": _shape,
                "preview": __pystudio_shorten__(_value, __PREVIEW_CHARS__),
            }
        )
    return _json.dumps(_rows)


def __pystudio_frame__(name, start, stop, sort=None, ascending=True):
    """Describe a slice of a table-like value as JSON. Defined by pystudio."""
    import json as _json

    def _cell(value):
        try:
            text = " ".join(str(value).split())
        except Exception:
            return "<str failed>"
        if len(text) > __CELL_CHARS__:
            text = text[: __CELL_CHARS__ - 1] + "\\u2026"
        return text

    _ns = get_ipython().user_ns
    if name not in _ns:
        return _json.dumps({"kind": "missing"})
    _value = _ns[name]
    _start, _stop = int(start), int(stop)

    # DataFrame-alikes: positional slicing plus named columns.
    if hasattr(_value, "iloc") and hasattr(_value, "columns"):
        _frame = _value
        _lookup = {str(_column): _column for _column in _frame.columns}
        if sort is not None and sort in _lookup:
            try:
                _frame = _frame.sort_values(_lookup[sort], ascending=bool(ascending))
            except Exception:
                pass
        _keep = list(_frame.columns)[:__MAX_COLUMNS__]
        _view = _frame.iloc[_start:_stop][_keep]
        return _json.dumps(
            {
                "kind": "dataframe",
                "columns": [str(_column) for _column in _keep],
                "index": [_cell(_label) for _label in _view.index],
                "rows": [
                    [_cell(_item) for _item in _row]
                    for _row in _view.itertuples(index=False, name=None)
                ],
                "rows_total": int(_frame.shape[0]),
                "columns_total": int(_frame.shape[1]),
                "start": _start,
            }
        )

    # Series-alikes: one column, keep the index.
    if hasattr(_value, "iloc"):
        _series = _value
        if sort is not None:
            try:
                _series = _series.sort_values(ascending=bool(ascending))
            except Exception:
                pass
        _view = _series.iloc[_start:_stop]
        _label = getattr(_series, "name", None)
        return _json.dumps(
            {
                "kind": "series",
                "columns": [str(_label) if _label is not None else "value"],
                "index": [_cell(_position) for _position in _view.index],
                "rows": [[_cell(_item)] for _item in _view],
                "rows_total": int(len(_series)),
                "columns_total": 1,
                "start": _start,
            }
        )

    # Arrays of one or two dimensions; a 1-d array becomes a single column.
    _dims = getattr(_value, "shape", None)
    if isinstance(_dims, tuple) and 1 <= len(_dims) <= 2:
        _array = _value.reshape(-1, 1) if len(_dims) == 1 else _value
        _columns_total = int(_array.shape[1])
        _view = _array[_start:_stop, :__MAX_COLUMNS__]
        _shown = min(_columns_total, __MAX_COLUMNS__)
        return _json.dumps(
            {
                "kind": "array",
                "columns": [str(_position) for _position in range(_shown)],
                "index": [str(_position) for _position in range(_start, _start + len(_view))],
                "rows": [[_cell(_item) for _item in _row] for _row in _view],
                "rows_total": int(_array.shape[0]),
                "columns_total": _columns_total,
                "start": _start,
            }
        )

    return _json.dumps({"kind": "other"})


__pystudio_figures__ = {}
__pystudio_plot_room__ = []


def __pystudio_view__(width, height):
    """Record the size of the plot pane, in pixels. Defined by pystudio."""
    __pystudio_plot_room__[:] = [int(width), int(height)]
    return ""


def __pystudio_draw__(figure, room=None, window=(0.0, 0.0, 1.0, 1.0), size=None, fmt="png"):
    """Render part of a figure to fit ``room`` pixels. Defined by pystudio.

    ``window`` is left, top, right, bottom in fractions of the figure, measured
    from the top left. ``size`` lays the figure out again at that many inches.
    """
    import io as _io
    import math as _math

    from matplotlib.transforms import Bbox as _Bbox

    _authored = tuple(figure.get_size_inches())
    try:
        # A figure laid out for the pane fills it, margins and all. One kept as
        # its author made it is trimmed, the way the inline backend trims it.
        _box = None
        if size:
            figure.set_size_inches(*size)
        else:
            figure.draw_without_rendering()
            _box = figure.get_tightbbox()
        if (
            _box is not None
            and all(_math.isfinite(_edge) for _edge in _box.extents)
            and _box.width > 0
            and _box.height > 0
        ):
            _box = _box.padded(0.1)
        else:
            _box = figure.bbox_inches
        _left, _top, _right, _bottom = window
        _region = _Bbox.from_extents(
            _box.x0 + _left * _box.width,
            _box.y1 - _bottom * _box.height,
            _box.x0 + _right * _box.width,
            _box.y1 - _top * _box.height,
        )
        _dpi = figure.dpi
        if room:
            _dpi = min(room[0] / _region.width, room[1] / _region.height)
        _buffer = _io.BytesIO()
        figure.savefig(_buffer, format=fmt, dpi=_dpi, bbox_inches=_region)
        return _buffer.getvalue()
    finally:
        if size:
            figure.set_size_inches(*_authored)


def __pystudio_png__(figure):
    """Keep a figure for later renders, and draw it for the pane. Defined by pystudio."""
    import base64 as _base64

    if not figure.axes and not figure.lines:
        return None
    try:
        _data = __pystudio_draw__(figure, tuple(__pystudio_plot_room__) or None)
    except Exception:
        from IPython.core.pylabtools import print_figure as _print_figure

        return _print_figure(figure, base64=True)

    _key = next((_k for _k, _f in __pystudio_figures__.items() if _f is figure), None)
    if _key is None:
        _key = __pystudio_png__.count = getattr(__pystudio_png__, "count", 0) + 1
    else:
        del __pystudio_figures__[_key]
    __pystudio_figures__[_key] = figure
    while len(__pystudio_figures__) > __MAX_FIGURES__:
        del __pystudio_figures__[next(iter(__pystudio_figures__))]

    _title = ""
    try:
        _title = figure.get_suptitle() or next(
            (_axes.get_title() for _axes in figure.axes if _axes.get_title()), ""
        )
    except Exception:
        pass
    _meta = {"pystudio": {"figure": _key, "title": " ".join(str(_title).split())}}
    return _base64.b64encode(_data).decode("ascii"), _meta


def __pystudio_render__(key, room, window, size=None, fmt="png"):
    """Draw a kept figure again, as base64; empty if it is gone. Defined by pystudio."""
    import base64 as _base64

    _figure = __pystudio_figures__.get(key)
    if _figure is None:
        return ""
    return _base64.b64encode(__pystudio_draw__(_figure, room, window, size, fmt)).decode("ascii")


try:
    from matplotlib.figure import Figure as _Figure

    get_ipython().display_formatter.formatters["image/png"].for_type(_Figure, __pystudio_png__)
    del _Figure
except Exception:
    pass
'''

SETUP = (
    _SETUP_TEMPLATE.replace("__PREVIEW_CHARS__", str(PREVIEW_CHARS))
    .replace("__CELL_CHARS__", str(CELL_CHARS))
    .replace("__MAX_COLUMNS__", str(MAX_COLUMNS))
    .replace("__MAX_FIGURES__", str(MAX_FIGURES))
)


def frame_expr(
    name: str,
    start: int,
    stop: int,
    *,
    sort: str | None = None,
    ascending: bool = True,
) -> str:
    """The expression that fetches one page of a table-like value."""
    return f"__pystudio_frame__({name!r}, {int(start)}, {int(stop)}, {sort!r}, {bool(ascending)!r})"


def view_expr(width: int, height: int) -> str:
    """The expression that tells the kernel how big the plot pane is, in pixels."""
    return f"__pystudio_view__({int(width)}, {int(height)})"


def render_expr(
    figure: int,
    room: tuple[int, int],
    window: tuple[float, float, float, float],
    *,
    size: tuple[float, float] | None = None,
    fmt: str = "png",
) -> str:
    """The expression that draws part of a kept figure again."""
    return (
        f"__pystudio_render__({int(figure)}, {tuple(int(side) for side in room)!r}, "
        f"{tuple(float(edge) for edge in window)!r}, "
        f"{tuple(float(side) for side in size) if size else None!r}, {fmt!r})"
    )


@dataclass(frozen=True)
class Variable:
    """One row of the variable explorer."""

    name: str
    type: str
    shape: str = ""
    preview: str = ""


@dataclass(frozen=True)
class Frame:
    """One page of a table-like value, as the viewer needs it."""

    kind: str
    columns: list[str] = field(default_factory=list)
    index: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    rows_total: int = 0
    columns_total: int = 0
    start: int = 0

    @property
    def viewable(self) -> bool:
        return self.kind in ("dataframe", "series", "array")


def _payload(text_plain: str) -> object:
    """Undo the repr the kernel wraps a returned string in, then read the JSON."""
    payload: object = text_plain
    with contextlib.suppress(ValueError, SyntaxError):
        payload = ast.literal_eval(text_plain)
    if not isinstance(payload, str):
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def parse_render(text_plain: str) -> bytes | None:
    """Turn the ``text/plain`` of a render reply into the file's bytes."""
    payload: object = None
    with contextlib.suppress(ValueError, SyntaxError):
        payload = ast.literal_eval(text_plain)
    if not isinstance(payload, str) or not payload:
        return None
    try:
        return base64.b64decode(payload)
    except ValueError:
        return None


def parse_probe(text_plain: str) -> list[Variable]:
    """Turn the ``text/plain`` of a snapshot reply into variables."""
    rows = _payload(text_plain)
    if not isinstance(rows, list):
        return []
    return [
        Variable(
            name=str(row.get("name", "")),
            type=str(row.get("type", "")),
            shape=str(row.get("shape", "")),
            preview=str(row.get("preview", "")),
        )
        for row in rows
        if isinstance(row, dict)
    ]


def parse_frame(text_plain: str) -> Frame:
    """Turn the ``text/plain`` of a table reply into a page."""
    data = _payload(text_plain)
    if not isinstance(data, dict):
        return Frame(kind="other")
    return Frame(
        kind=str(data.get("kind", "other")),
        columns=[str(column) for column in data.get("columns", ())],
        index=[str(label) for label in data.get("index", ())],
        rows=[[str(cell) for cell in row] for row in data.get("rows", ()) if isinstance(row, list)],
        rows_total=int(data.get("rows_total", 0) or 0),
        columns_total=int(data.get("columns_total", 0) or 0),
        start=int(data.get("start", 0) or 0),
    )
