# %%
# The plot pane, feature by feature
# ============================================================================
#
# Open this file with:   uv run pystudio examples/plots.py
#
# Send each cell with \c, then try the keys its comment names. They work when
# the plot pane has focus: ctrl+g 4, or click it.
#
#   + - 0      zoom in, zoom out, fit        f or enter   fill the screen
#   h j k l    pan while zoomed in           a            lay out for the pane
#   [ ]        previous, next figure         g            gallery
#   d D        delete one, delete all        o y          open outside, copy
#   ctrl+s     save PNG                      S P          save SVG, PDF
#
#   ctrl+g < >   move the divider between the columns
#   ctrl+g + -   grow or shrink the focused pane
#   ctrl+g p     next layout: default, wide plots, plots only
#
# Press \c to move on.

# %%
# Cell 2 --- imports. Altair draws PNGs here, so its charts land in the pane.

import altair as alt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display

alt.renderers.enable("png", scale_factor=2)

rng = np.random.default_rng(0)

# %%
# Cell 3 --- sharp zoom.
#
# 20 000 points with a tight cluster hidden near (2, 2). Focus the plots, then
# roll the wheel over the cluster, or press + a few times and pan with h j k l.
# The picture first enlarges as it is, blurry, then the kernel draws that region
# again and the points come out crisp. 0 fits it back.

cloud = pd.DataFrame(rng.normal(0, 1.5, size=(20_000, 2)), columns=["x", "y"])
cluster = pd.DataFrame(rng.normal(2, 0.02, size=(300, 2)), columns=["x", "y"])

fig, ax = plt.subplots()
ax.scatter(cloud.x, cloud.y, s=1, alpha=0.4)
ax.scatter(cluster.x, cluster.y, s=1, color="crimson")
ax.annotate("zoom in here", (2, 2), (3.5, 4.5), arrowprops={"arrowstyle": "->"}, fontsize=7)
ax.set_title("a cluster worth zooming into")
plt.show()

# %%
# Cell 4 --- small text, and filling the screen.
#
# Nine panels are unreadable in a third of the screen. Press f, or double
# click: the pane takes the whole screen and the figure is drawn again for it.
# f or escape gives the screen back.

fig, axes = plt.subplots(3, 3, figsize=(9, 7), sharex=True)
t = np.linspace(0, 2 * np.pi, 300)
for k, ax in enumerate(axes.flat, start=1):
    ax.plot(t, np.sin(k * t) * np.exp(-t / 4))
    ax.set_title(f"mode {k}", fontsize=8)
    ax.tick_params(labelsize=6)
fig.suptitle("nine damped modes")
fig.tight_layout()
plt.show()

# %%
# Cell 5 --- laying a figure out for the pane.
#
# This one is far wider than the pane, so it sits in a thin strip. Press a: the
# kernel lays it out again at the pane's own proportions, and the caption says
# "fills pane". Resize the pane (ctrl+g + or drag a border) and it follows.
# Press a again for the size the code gave it.

fig, ax = plt.subplots(figsize=(14, 2.5))
walk = rng.normal(size=2_000).cumsum()
ax.plot(walk, linewidth=0.8)
ax.set_title("a random walk, drawn very wide")
ax.set_xlabel("step")
plt.show()

# %%
# Cell 6 --- an Altair chart, as a picture.
#
# vl-convert renders it to a PNG, so it shows in the pane and zooms. Only
# matplotlib figures are drawn again by the kernel, so this one enlarges the
# picture it arrived as; scale_factor=2 above is what keeps that readable.

sales = pd.DataFrame(
    {
        "month": np.tile(pd.date_range("2025-01-01", periods=12, freq="MS"), 3),
        "region": np.repeat(["north", "south", "west"], 12),
        "units": rng.poisson(120, 36) + np.tile(np.arange(12) * 6, 3),
    }
)

alt.Chart(sales, title="units sold by region").mark_line(point=True).encode(
    x=alt.X("month:T", title=None),
    y=alt.Y("units:Q", title="units"),
    color="region:N",
).properties(width=420, height=260).show()

# %%
# Cell 7 --- an interactive chart.
#
# Without the PNG renderer Altair produces a web page. The pane cannot draw
# that, so it keeps an entry for it: press o to open it in the browser, where
# hovering a point shows its values.

with alt.renderers.enable("html"):
    display(
        alt.Chart(sales, title="hover me in the browser")
        .mark_circle(size=80)
        .encode(x="month:T", y="units:Q", color="region:N", tooltip=["month", "region", "units"])
        .interactive()
    )

# %%
# Cell 8 --- one output, updated in place.
#
# The figure is shown once and then replaced four times. The history gains one
# entry, not five: watch the count in the caption.

fig, ax = plt.subplots()
(line,) = ax.plot([], [])
ax.set_xlim(0, 50)
ax.set_ylim(-12, 12)
ax.set_title("updated in place")
handle = display(fig, display_id=True)
steps = rng.normal(size=50).cumsum()
for stop in (10, 20, 30, 40, 50):
    line.set_data(range(stop), steps[:stop])
    handle.update(fig)
plt.close(fig)

# %%
# Cell 9 --- a few more, for the history.
#
# Press g: every figure so far as thumbnails. Move with h j k l, enter shows
# one, d deletes it, escape closes. Back in the pane, [ and ] step through
# them, d deletes the one on screen and D clears the lot.

for name, draw in {
    "histogram": lambda ax: ax.hist(rng.gamma(2.0, 2.0, 5_000), bins=60),
    "bars": lambda ax: ax.bar(list("abcdef"), rng.integers(3, 20, 6)),
    "heatmap": lambda ax: ax.imshow(rng.normal(size=(30, 30)).cumsum(axis=0), aspect="auto"),
}.items():
    fig, ax = plt.subplots(figsize=(7, 4))
    draw(ax)
    ax.set_title(name)
plt.show()

# %%
# Cell 10 --- getting a figure out.
#
# With a figure on screen:
#
#   ctrl+s   plot-<time>.png in the working directory
#   S, P     the same as SVG and PDF, drawn by the kernel as vectors
#   o        open it in the desktop's image viewer
#   y        copy it to the clipboard as an image
#
# S and P need a matplotlib figure the kernel still holds. Restart the kernel
# with ctrl+g r and try S again: the figures are still here and still zoom, as
# pictures, but the caption says the kernel no longer has them.

print("nothing to run here; try the keys above")

# %%
# Cell 11 --- room for the plots.
#
#   ctrl+g > > >   widen the editor; ctrl+g < < < widens the plots instead
#   ctrl+g 4, then ctrl+g + + +   make the plot pane taller
#   ctrl+g p       wide plots; again for plots only; again for the default
#
# The resize keys stay live after the first press, and any other key ends
# that. The borders between panes also drag with the mouse.

print("done")
