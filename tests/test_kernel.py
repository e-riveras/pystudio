"""The kernel layer against a real kernel."""

from __future__ import annotations

import asyncio

from pystudio import messages as m
from pystudio.kernel import KernelSession

from .conftest import Recorder


def idle(status: m.KernelStatus) -> bool:
    return status.state == "idle"


async def test_execute_result(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("2 + 2")
    result = await recorder.wait_for(m.ExecuteResult)
    assert result.data["text/plain"] == "4"
    assert result.execution_count == 1


async def test_execute_input_is_echoed(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("2 + 2")
    echo = await recorder.wait_for(m.ExecuteInput)
    assert echo.code == "2 + 2"


async def test_stream_output(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("print('hi')")
    stream = await recorder.wait_for(m.StreamOutput)
    assert stream.name == "stdout"
    assert stream.text == "hi\n"


async def test_error_carries_traceback(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("1 / 0")
    error = await recorder.wait_for(m.KernelError)
    assert error.ename == "ZeroDivisionError"
    assert any("ZeroDivisionError" in line for line in error.traceback)


async def test_status_goes_busy_then_idle(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("2 + 2")
    await recorder.wait_for(m.KernelStatus, match=lambda s: s.state == "busy")
    await recorder.wait_for(m.KernelStatus, match=idle)


async def test_setup_cell_stays_hidden(recorder: Recorder, tmp_path) -> None:
    session = KernelSession(recorder, cwd=tmp_path)
    await session.start()
    try:
        await recorder.wait_for(m.KernelStatus, match=idle)
        assert recorder.of(m.ExecuteInput) == []
        assert recorder.of(m.ExecuteResult) == []
    finally:
        await session.shutdown()


async def test_probe_reports_variables(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("x = 41 + 1")
    await recorder.wait_for(m.KernelStatus, match=idle)

    await kernel.probe_variables()
    snapshot = await recorder.wait_for(m.VariablesSnapshot)
    variables = {variable.name: variable for variable in snapshot.variables}
    assert variables["x"].type == "int"
    assert variables["x"].preview == "42"


async def test_probe_emits_nothing_else(kernel: KernelSession, recorder: Recorder) -> None:
    """A probe must not look like an execution, or it retriggers itself forever."""
    recorder.clear()
    await kernel.probe_variables()
    await recorder.wait_for(m.VariablesSnapshot)
    assert recorder.of(m.KernelStatus) == []
    assert recorder.of(m.ExecuteInput) == []


async def test_restart_clears_the_namespace(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("y = 1")
    await recorder.wait_for(m.KernelStatus, match=idle)

    await kernel.restart()
    emptied = await recorder.wait_for(m.VariablesSnapshot)
    assert emptied.variables == []

    recorder.clear()
    await kernel.probe_variables()
    snapshot = await recorder.wait_for(m.VariablesSnapshot)
    assert "y" not in {variable.name for variable in snapshot.variables}


async def test_interrupt_raises_keyboard_interrupt(
    kernel: KernelSession, recorder: Recorder
) -> None:
    await kernel.execute("import time\nwhile True:\n    time.sleep(0.05)\n")
    await recorder.wait_for(m.KernelStatus, match=lambda s: s.state == "busy")
    await asyncio.sleep(0.3)
    await kernel.interrupt()
    error = await recorder.wait_for(m.KernelError)
    assert error.ename == "KeyboardInterrupt"


async def test_completion(kernel: KernelSession) -> None:
    reply = await kernel.complete("prin", 4)
    assert "print" in reply["matches"]


async def test_figure_arrives_as_png(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.show()\n")
    display = await recorder.wait_for(m.DisplayData)
    assert "image/png" in display.data


async def test_barrier_waits_for_queued_work(kernel: KernelSession, recorder: Recorder) -> None:
    """A reply to a later request proves the earlier executions are done."""
    await kernel.execute("import time\ntime.sleep(0.6)\nmarker = 'done'\n")
    await kernel.barrier()

    recorder.clear()
    await kernel.probe_variables()
    snapshot = await recorder.wait_for(m.VariablesSnapshot)
    assert "marker" in {variable.name for variable in snapshot.variables}
