"""Variable snapshots: the parsing, then the round trip through a kernel."""

from __future__ import annotations

import json

from pystudio import messages as m
from pystudio.introspect import parse_probe
from pystudio.kernel import KernelSession

from .conftest import Recorder


def test_parse_probe_unwraps_the_repr() -> None:
    rows = [{"name": "x", "type": "int", "shape": "", "preview": "42"}]
    variables = parse_probe(repr(json.dumps(rows)))
    assert len(variables) == 1
    assert variables[0].name == "x"
    assert variables[0].preview == "42"


def test_parse_probe_survives_garbage() -> None:
    assert parse_probe("not a repr at all") == []
    assert parse_probe(repr("{oops")) == []
    assert parse_probe(repr(json.dumps({"not": "a list"}))) == []


async def test_shapes_and_module_filtering(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute(
        "import numpy as np\n"
        "import pandas as pd\n"
        "arr = np.zeros(4)\n"
        "df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})\n"
        "names = ['a', 'b', 'c']\n"
    )
    await recorder.wait_for(m.KernelStatus, match=lambda s: s.state == "idle")

    await kernel.probe_variables()
    snapshot = await recorder.wait_for(m.VariablesSnapshot)
    variables = {variable.name: variable for variable in snapshot.variables}

    assert variables["arr"].type == "ndarray"
    assert variables["arr"].shape == "(4,)"
    assert variables["df"].type == "DataFrame"
    assert variables["df"].shape == "(3, 2)"
    assert variables["names"].shape == "3"

    # Imported modules are noise in a variable explorer.
    assert "np" not in variables
    assert "pd" not in variables


async def test_long_previews_are_truncated(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("big = list(range(500))")
    await recorder.wait_for(m.KernelStatus, match=lambda s: s.state == "idle")

    await kernel.probe_variables()
    snapshot = await recorder.wait_for(m.VariablesSnapshot)
    variables = {variable.name: variable for variable in snapshot.variables}
    assert len(variables["big"].preview) <= 60
    assert variables["big"].preview.endswith("…")
