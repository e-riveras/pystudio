"""Make docs/screenshot.png.

    uv run python docs/screenshot.py <empty work directory> docs/screenshot.png

The app runs headless on the guided tour and Textual exports the screen as SVG.
A headless run has no graphics protocol, so the plot pane would show character
blocks. The figure is instead rendered by the kernel and placed over the pane,
which is what a terminal with Kitty graphics or Sixel draws there. The picture
is therefore a composite and not a capture of a terminal. Needs `rsvg-convert`.
"""

import asyncio
import base64
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from pystudio.__main__ import write_demo
from pystudio.app import PyStudioApp

WORK, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
CHAR_W, LINE_H = 12.2, 24.4  # Rich's SVG export: 20px text, 0.61 wide, 1.22 line height
MARK = re.compile(r"^\s*#\s*%%")


def cells(source: str) -> list[str]:
    chunks: list[list[str]] = [[]]
    for line in source.splitlines():
        if MARK.match(line):
            chunks.append([])
            continue
        chunks[-1].append(line)
    return ["\n".join(chunk) for chunk in chunks if "\n".join(chunk).strip()]


async def until(predicate, timeout: float = 60) -> None:
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise SystemExit("timed out")
        await asyncio.sleep(0.05)


async def main() -> None:
    os.chdir(WORK)
    demo = write_demo(WORK)
    app = PyStudioApp(path=Path(demo.name), clean=True)
    async with app.run_test(size=(150, 44)) as pilot:
        await until(lambda: app._kernel_ready and app.editor.channel > 0)
        for cell in cells(demo.read_text())[:7]:
            assert await app.kernel.run(cell) == "ok"
        await until(lambda: app.plots.count == 2)
        await pilot.pause(1.0)
        app.plots.action_previous()
        app.editor.rpc.notify("nvim_command", "call search('Cell 6 ---') | normal! zt4j")
        await pilot.pause(1.5)
        figure = app.plots.current
        region = app.plots.image_widget.region
        png = await app.kernel.render_figure(
            figure.figure_id, (round(region.width * CHAR_W * 2), round(region.height * LINE_H * 2))
        )
        app.plots.image_widget.display = False
        await pilot.pause(0.3)
        svg = app.export_screenshot(title="pystudio")
    image = (
        f'<image x="{region.x * CHAR_W:.1f}" y="{region.y * LINE_H + 1.5:.1f}" '
        f'width="{region.width * CHAR_W:.1f}" height="{region.height * LINE_H:.1f}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'href="data:image/png;base64,{base64.b64encode(png).decode()}"/>'
    )
    # The cells are drawn in one group; the figure goes on top of it, in its coordinates.
    marker = svg.rindex("</g>", 0, svg.rindex("</g>"))
    svg = svg[:marker] + image + svg[marker:]
    (WORK / "screenshot.svg").write_text(svg)
    subprocess.run(
        ["rsvg-convert", "-z", "1.5", "-o", str(OUT), str(WORK / "screenshot.svg")], check=True
    )


asyncio.run(main())
