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


SETUP_FRAMES = (
    "import numpy as np\n"
    "import pandas as pd\n"
    "frame = pd.DataFrame({'a': [3, 1, 2], 'b': ['x', 'y', 'z']})\n"
    "series = pd.Series([1, 2, 3], name='vals')\n"
    "grid = np.arange(6).reshape(3, 2)\n"
    "flat = np.arange(4)\n"
    "scalar = 5\n"
    "wide = pd.DataFrame({'n': range(500)})\n"
)


async def frames_ready(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute(SETUP_FRAMES)
    await recorder.wait_for(m.KernelStatus, match=lambda s: s.state == "idle")
    recorder.clear()


async def test_fetch_frame_reads_a_dataframe(kernel: KernelSession, recorder: Recorder) -> None:
    await frames_ready(kernel, recorder)
    page = await kernel.fetch_frame("frame", 0, 10)
    assert page.kind == "dataframe"
    assert page.columns == ["a", "b"]
    assert page.index == ["0", "1", "2"]
    assert page.rows == [["3", "x"], ["1", "y"], ["2", "z"]]
    assert (page.rows_total, page.columns_total) == (3, 2)


async def test_fetch_frame_sorts_in_the_kernel(kernel: KernelSession, recorder: Recorder) -> None:
    await frames_ready(kernel, recorder)
    ascending = await kernel.fetch_frame("frame", 0, 10, sort="a")
    assert [row[0] for row in ascending.rows] == ["1", "2", "3"]

    descending = await kernel.fetch_frame("frame", 0, 10, sort="a", ascending=False)
    assert [row[0] for row in descending.rows] == ["3", "2", "1"]


async def test_fetch_frame_pages(kernel: KernelSession, recorder: Recorder) -> None:
    await frames_ready(kernel, recorder)
    page = await kernel.fetch_frame("wide", 100, 105)
    assert page.rows_total == 500
    assert [row[0] for row in page.rows] == ["100", "101", "102", "103", "104"]
    assert page.index == ["100", "101", "102", "103", "104"]


async def test_fetch_frame_handles_series_and_arrays(
    kernel: KernelSession, recorder: Recorder
) -> None:
    await frames_ready(kernel, recorder)

    page = await kernel.fetch_frame("series", 0, 10)
    assert page.kind == "series"
    assert page.columns == ["vals"]
    assert page.rows == [["1"], ["2"], ["3"]]

    page = await kernel.fetch_frame("grid", 0, 10)
    assert page.kind == "array"
    assert page.columns == ["0", "1"]
    assert page.rows == [["0", "1"], ["2", "3"], ["4", "5"]]
    assert (page.rows_total, page.columns_total) == (3, 2)

    # A 1-d array becomes a single column.
    page = await kernel.fetch_frame("flat", 0, 10)
    assert page.kind == "array"
    assert page.rows == [["0"], ["1"], ["2"], ["3"]]


async def test_fetch_frame_rejects_the_unviewable(
    kernel: KernelSession, recorder: Recorder
) -> None:
    await frames_ready(kernel, recorder)
    assert (await kernel.fetch_frame("scalar", 0, 10)).kind == "other"
    assert (await kernel.fetch_frame("nothing_here", 0, 10)).kind == "missing"
    assert not (await kernel.fetch_frame("scalar", 0, 10)).viewable


async def test_fetch_frame_stays_out_of_the_console(
    kernel: KernelSession, recorder: Recorder
) -> None:
    await frames_ready(kernel, recorder)
    await kernel.fetch_frame("frame", 0, 10)
    assert recorder.messages == []
