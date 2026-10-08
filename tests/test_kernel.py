"""The kernel layer against a real kernel."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import stat
import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage

from pystudio import messages as m
from pystudio.introspect import MAX_FIGURES
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


async def test_runs_in_the_given_interpreter(recorder: Recorder, tmp_path) -> None:
    python = Path(sys.executable)
    session = KernelSession(recorder, python=python, cwd=tmp_path)
    await session.start()
    try:
        await session.execute("import sys; sys.executable")
        result = await recorder.wait_for(m.ExecuteResult)
        assert result.data["text/plain"].strip("'\"") == str(python)
    finally:
        await session.shutdown()


async def test_attaches_to_a_running_kernel(kernel: KernelSession, tmp_path) -> None:
    """A second session shares the first one's namespace and leaves it running."""
    await kernel.execute("shared = 'from the owner'")
    await kernel.barrier()

    seen = Recorder()
    attached = KernelSession(seen, connection_file=kernel.connection_file, cwd=tmp_path)
    await attached.start()
    try:
        assert not attached.owned
        await attached.execute("shared")
        result = await seen.wait_for(m.ExecuteResult)
        assert result.data["text/plain"] == "'from the owner'"
    finally:
        await attached.shutdown()

    assert await kernel.complete("shar", 4)


async def test_attached_session_can_interrupt(
    kernel: KernelSession, recorder: Recorder, tmp_path
) -> None:
    attached = KernelSession(Recorder(), connection_file=kernel.connection_file, cwd=tmp_path)
    await attached.start()
    try:
        await recorder.settle()
        await kernel.execute("import time\nwhile True:\n    time.sleep(0.05)\n")
        await recorder.wait_for(m.KernelStatus, match=lambda s: s.state == "busy")
        await asyncio.sleep(0.3)
        await attached.interrupt()
        error = await recorder.wait_for(m.KernelError)
        assert error.ename == "KeyboardInterrupt"
    finally:
        await attached.shutdown()


async def test_kernel_listens_on_private_sockets_not_tcp(recorder: Recorder, tmp_path) -> None:
    """Jupyter does not encrypt, so the kernel must not be reachable over TCP."""
    session = KernelSession(recorder, cwd=tmp_path)
    await session.start()
    try:
        info = json.loads(session.connection_file.read_text())
        assert info["transport"] == "ipc"
        sockets = Path(info["ip"]).parent
        assert stat.S_IMODE(sockets.stat().st_mode) == 0o700
        assert stat.S_IMODE(session.connection_file.stat().st_mode) == 0o600
    finally:
        await session.shutdown()
    assert not sockets.exists()


async def test_evaluate_is_quiet(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("answer = 41")
    await recorder.settle()

    assert await kernel.evaluate("answer + 1") == (True, "42")
    assert recorder.of(m.ExecuteInput) == []
    assert recorder.of(m.ExecuteResult) == []
    assert recorder.of(m.KernelStatus) == []


async def test_evaluate_reports_the_error(kernel: KernelSession) -> None:
    ok, text = await kernel.evaluate("missing_name")
    assert not ok
    assert "NameError" in text


async def test_variables_are_awaited(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute("answer = 41")
    await kernel.barrier()
    assert "answer" in {variable.name for variable in await kernel.variables()}


async def test_run_waits_and_reports_the_status(kernel: KernelSession, recorder: Recorder) -> None:
    assert await kernel.run("import time; time.sleep(0.3); slept = True") == "ok"
    assert await kernel.evaluate("slept") == (True, "True")
    assert await kernel.run("1 / 0") == "error"
    await recorder.wait_for(m.KernelError)


async def test_restart_releases_a_waiting_run(kernel: KernelSession) -> None:
    from pystudio.kernel import KernelReset

    waiting = asyncio.create_task(kernel.run("import time; time.sleep(30)"))
    await asyncio.sleep(0.3)
    await kernel.restart()
    try:
        await asyncio.wait_for(waiting, 5)
    except KernelReset:
        return
    raise AssertionError("the run was not released")


PLOT = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot([1, 2, 3])\n"


def figure_id(message: m.DisplayData) -> int:
    return message.metadata["image/png"]["pystudio"]["figure"]


def size_of(png: bytes) -> tuple[int, int]:
    return PILImage.open(io.BytesIO(png)).size


async def test_figure_is_drawn_to_fit_the_pane(kernel: KernelSession, recorder: Recorder) -> None:
    kernel.set_plot_view(900, 300)
    await kernel.execute(PLOT + "ax.set_title('a  title')\n")
    shown = await recorder.wait_for(m.DisplayData)

    width, height = size_of(base64.b64decode(shown.data["image/png"]))
    assert height == pytest.approx(300, abs=2)
    assert width < 900
    assert shown.metadata["image/png"]["pystudio"]["title"] == "a title"


async def test_kept_figure_is_drawn_again(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute(PLOT)
    shown = await recorder.wait_for(m.DisplayData)
    recorder.clear()

    whole = await kernel.render_figure(figure_id(shown), (1200, 1200))
    part = await kernel.render_figure(figure_id(shown), (800, 400), (0.25, 0.25, 0.75, 0.5))

    assert whole is not None and part is not None
    assert max(size_of(whole)) == pytest.approx(1200, abs=2)
    # A quarter of the height and half of the width: wider than the room, so
    # it is the width that fills it.
    assert size_of(part)[0] == pytest.approx(800, abs=2)
    assert size_of(part)[1] < 400
    assert not recorder.of(m.DisplayData)


async def test_figure_is_laid_out_again_at_another_size(
    kernel: KernelSession, recorder: Recorder
) -> None:
    await kernel.execute(PLOT)
    shown = await recorder.wait_for(m.DisplayData)

    wide = await kernel.render_figure(figure_id(shown), (1000, 250), size=(10.0, 2.5))
    again = await kernel.render_figure(figure_id(shown), (640, 480))

    assert wide is not None and again is not None
    assert size_of(wide) == pytest.approx((1000, 250), abs=2)
    # The figure the user made keeps the size they gave it.
    assert size_of(again)[0] / size_of(again)[1] == pytest.approx(4 / 3, rel=0.1)


async def test_figure_can_be_drawn_as_a_vector(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute(PLOT)
    shown = await recorder.wait_for(m.DisplayData)

    svg = await kernel.render_figure(figure_id(shown), (640, 480), fmt="svg")

    assert svg is not None and b"<svg" in svg


async def test_only_recent_figures_are_kept(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute(PLOT)
    first = await recorder.wait_for(m.DisplayData)
    await kernel.run(f"for _ in range({MAX_FIGURES}):\n    plt.figure().gca().plot([1, 2])\n")

    assert await kernel.render_figure(figure_id(first), (100, 100)) is None


async def test_restart_forgets_the_figures(kernel: KernelSession, recorder: Recorder) -> None:
    await kernel.execute(PLOT)
    shown = await recorder.wait_for(m.DisplayData)

    await kernel.restart()

    assert await kernel.render_figure(figure_id(shown), (100, 100)) is None
