"""Run every cell of the guided tour, so the demo cannot rot unnoticed."""

from __future__ import annotations

import re
from pathlib import Path

from pystudio import messages as m
from pystudio.kernel import KernelSession

from .conftest import Recorder

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo.py"
MARKER = re.compile(r"^\s*#\s*%%")


def cells(source: str) -> list[str]:
    """Split a `# %%` script the way send.lua does: markers are not code."""
    chunks: list[list[str]] = [[]]
    for line in source.splitlines():
        if MARKER.match(line):
            chunks.append([])
            continue
        chunks[-1].append(line)
    return ["\n".join(chunk) for chunk in chunks if "\n".join(chunk).strip()]


def test_the_demo_is_made_of_cells() -> None:
    found = cells(DEMO.read_text(encoding="utf-8"))
    assert len(found) == 14
    # The interactive cells must stay commented out, or running the tour
    # unattended would block on input() or spin forever.
    live = [
        line
        for line in "\n".join(found).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not [line for line in live if "while True" in line]
    assert not [line for line in live if "input(" in line]


async def test_every_demo_cell_runs(kernel: KernelSession, recorder: Recorder) -> None:
    source = cells(DEMO.read_text(encoding="utf-8"))
    errors: dict[int, str] = {}
    figures = 0

    for index, cell in enumerate(source, start=1):
        recorder.clear()
        await kernel.execute(cell)
        # The barrier proves the cell finished; the idle that follows proves its
        # output has been delivered, so the messages below are this cell's.
        await kernel.barrier()
        await recorder.wait_for(
            m.KernelStatus, match=lambda status: status.state == "idle", timeout=90
        )
        for error in recorder.of(m.KernelError):
            errors[index] = error.ename
        figures += sum(1 for display in recorder.of(m.DisplayData) if "image/png" in display.data)

    # Nothing may fail, or replaying the tour with \a or \f would stop part way.
    assert errors == {}
    assert figures == 2

    recorder.clear()
    await kernel.probe_variables()
    snapshot = await recorder.wait_for(m.VariablesSnapshot)
    names = {variable.name: variable for variable in snapshot.variables}
    assert names["sales"].shape == "(24, 4)"
    assert names["grid"].shape == "(12, 4)"
    assert names["state"].preview == "'restored'"
    assert "np" not in names and "pd" not in names

    page = await kernel.fetch_frame("many", 0, 5)
    assert page.rows_total == 200_000
    assert page.columns == ["n", "root"]
