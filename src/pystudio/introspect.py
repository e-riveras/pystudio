"""Variable introspection inside the kernel, with no visible output.

``SETUP`` is run once, silently, when a kernel comes up. It defines
``__pystudio_inspect__`` in the user namespace, which returns a JSON string
describing every interesting name the user has bound.

Snapshots are taken with an ``execute_request`` that has empty ``code`` and asks
for ``PROBE_EXPR`` in ``user_expressions``. The result rides back on the
``execute_reply``, so nothing is added to the kernel's history and nothing is
published on iopub for the console to display.
"""

from __future__ import annotations

import ast
import contextlib
import json
from dataclasses import dataclass

PROBE_EXPR = "__pystudio_inspect__()"
"""Expression to pass in ``user_expressions`` to take a snapshot."""

PREVIEW_CHARS = 60

SETUP = f'''
try:
    get_ipython().run_line_magic("matplotlib", "inline")
except Exception:
    pass


def __pystudio_inspect__():
    """Describe the user namespace as a JSON string. Defined by pystudio."""
    import json as _json
    import types as _types

    _hidden = {{"In", "Out", "get_ipython", "exit", "quit", "open"}}
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

        try:
            _preview = " ".join(repr(_value).split())
        except Exception:
            _preview = "<repr failed>"
        if len(_preview) > {PREVIEW_CHARS}:
            _preview = _preview[: {PREVIEW_CHARS} - 1] + "…"

        _rows.append(
            {{
                "name": _name,
                "type": type(_value).__name__,
                "shape": _shape,
                "preview": _preview,
            }}
        )
    return _json.dumps(_rows)
'''


@dataclass(frozen=True)
class Variable:
    """One row of the variable explorer."""

    name: str
    type: str
    shape: str = ""
    preview: str = ""


def parse_probe(text_plain: str) -> list[Variable]:
    """Turn the ``text/plain`` of a probe reply into variables.

    The kernel sends back the *repr* of the JSON string the helper returned, so
    the quoting has to be undone before the JSON is read.
    """
    payload: object = text_plain
    with contextlib.suppress(ValueError, SyntaxError):
        payload = ast.literal_eval(text_plain)
    if not isinstance(payload, str):
        return []
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError:
        return []
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
