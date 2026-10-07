# %%
# pystudio guided tour
# ============================================================================
#
# Open this file with:   just demo        (or: uv run pystudio examples/demo.py)
#
# Keys used below. `\` is <localleader>; if you have your own <leader>, the same
# letters work there too unless they collided with your mappings, in which case
# `:echo g:pystudio_keys_skipped` says which ones.
#
#   \l   send this line (or a visual selection) and move down
#   \c   send this whole cell and jump to the next one
#   \a   send everything above this cell
#   \.   send the last thing again
#
#   ctrl+g 1   focus the editor        ctrl+g z   zoom the focused pane
#   ctrl+g 2   focus the console       ctrl+g i   interrupt the kernel
#   ctrl+g 3   focus the variables     ctrl+g r   restart the kernel
#   ctrl+g 4   focus the plots         ctrl+g q   quit
#   ctrl+g a   ask the assistant       ctrl+g k   pick another kernel
#
# Notice the rule drawn above each `# %%` below, and the faint wash over the
# cell your cursor is in. That wash is exactly what `\c` will send.
#
# Start here: press \c. Nothing runs, because a cell of comments has nothing to
# run, and the cursor jumps to cell 2.

# %%
# Cell 2 --- imports and a first look at the variable explorer.
#
# Press \c. Watch the variables pane on the right: `sales` and `rng` appear a
# moment after the kernel goes idle. Modules are deliberately hidden, so `pd`
# and `np` do not show up.

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

rng = np.random.default_rng(0)
sales = pd.DataFrame(
    {
        "region": ["north", "south", "east", "west"] * 6,
        "units": rng.integers(10, 99, 24),
        "price": rng.normal(20, 4, 24).round(2),
    }
)
sales["revenue"] = (sales["units"] * sales["price"]).round(2)

# %%
# Cell 3 --- one line at a time, the RStudio way.
#
# Put the cursor on the first line below and press \l four times. Each press
# sends one line and moves down, and the console echoes it as `In [n]:`.
# The last line prints, so you also see output land under its own prompt.

totals = sales.groupby("region")["revenue"].sum()
best = totals.idxmax()
worst = totals.idxmin()
print(f"best {best}, worst {worst}")

# %%
# Cell 4 --- the table viewer.
#
# Run this cell with \c, then:
#
#   1. ctrl+g 3            focus the variables pane
#   2. move to `sales`     and press enter
#   3. press right twice   to put the cell cursor on `units`
#   4. press s             sorts ascending, again sorts descending
#   5. click a header      does the same with the mouse
#   6. escape              closes the viewer
#
# The sort happens in the kernel, not in the loaded page, so it is the real
# order of the whole frame. The caption counts the rows it has fetched.

by_region = sales.pivot_table(index="region", values=["units", "revenue"], aggfunc="sum")

# %%
# Cell 5 --- paging. This frame is too big to load at once.
#
# Run it, then open `many` in the viewer and hold `down`. Rows arrive a page at
# a time, 200 per fetch, when the cursor comes within 20 rows of the end. The
# caption keeps count: "200 of 200000 rows", then 400, and so on.

many = pd.DataFrame({"n": np.arange(200_000), "root": np.sqrt(np.arange(200_000)).round(3)})

# %%
# Cell 6 --- plots.
#
# Run it and the figure appears in the plot pane. Kitty, Ghostty and WezTerm
# draw a real image; elsewhere you get half-cell blocks, and the status bar says
# which protocol is in use, so a blocky plot is not a bug.

figure, axes = plt.subplots(figsize=(7, 4))
totals.sort_values().plot.barh(ax=axes, color="#4c78a8")
axes.set_title("revenue by region")
axes.set_xlabel("revenue")
figure.tight_layout()
plt.show()

# %%
# Cell 7 --- a second figure, so there is a history to walk.
#
# Run it, then ctrl+g 4 to focus the plot pane and use `[` and `]` to step
# between the two. `ctrl+s` writes the current one to the working directory.

figure, axes = plt.subplots(figsize=(7, 4))
axes.scatter(sales["units"], sales["revenue"], c="#f58518")
axes.set_title("revenue against units")
axes.set_xlabel("units")
axes.set_ylabel("revenue")
figure.tight_layout()
plt.show()

# %%
# Cell 8 --- completion and history at the prompt.
#
# This cell has nothing to send. Press ctrl+g 2 to focus the console, then try:
#
#   sal<Tab>              completes to `sales`
#   sales.descr<Tab>      completes to `sales.describe`
#   sales.<Tab>           lists the candidates and inserts their common prefix
#   up / down             walk the history, which survives restarts
#
# Multi-line blocks work too. Type `for region in totals.index:` and press
# enter: the prompt waits instead of running, because the block is unfinished.
# Add `    print(region)`, then an empty line to close it.

# %%
# Cell 9 --- errors.
#
# Uncomment and run. The traceback keeps IPython's own colours, because the
# console renders the ANSI the kernel sent rather than re-formatting it. It stays
# commented out so that \a and \f, which stop at the first cell that fails, get
# past it.

# sales["nope"].sum()

# %%
# Cell 10 --- interrupting. Interactive only.
#
# Run this and the status bar goes busy and stays there. Press ctrl+g i (or run
# :PyStudioInterrupt from the editor) and it comes back as a KeyboardInterrupt
# traceback. The IDE stays responsive the whole time, because the kernel is a
# separate process.

# import time
#
# while True:
#     time.sleep(0.1)

# %%
# Cell 11 --- input(). Interactive only.
#
# Uncomment and run. The prompt at the bottom of the console turns into an
# answer box; type something and press enter.

# who = input("your name: ")
# print(f"hello {who}")

# %%
# Cell 12 --- restart, and replaying what came before.
#
# Press ctrl+g r. The kernel restarts and the variables pane empties.
#
# Now put the cursor in this cell and press \a. Every cell above runs again, one
# at a time and in order, and the namespace is back. That is the answer to the
# usual notebook problem of not knowing what state you are in. If a cell fails,
# the rest are not run, and the console says which one stopped it.
#
# `\.` sends the last thing again, which is handy while editing one line.

state = "restored"

# %%
# Cell 13 --- things the viewer does not open.
#
# Run this, then press enter on each of them in the variables pane. A Series and
# an array open in the viewer; the scalar and the dict print to the console
# instead, since there is no table to show.

one_column = sales["revenue"]
grid = rng.integers(0, 9, (12, 4))
answer = 42
config = {"alpha": 0.1, "beta": 0.9}

# %%
# Cell 14 --- it is a real Neovim.
#
# Nothing to run. Convince yourself the editor is not an imitation:
#
#   :w                     writes this file; pystudio has no save logic
#   <space>ff              your telescope mapping, inside the pane
#   qaciw...q then @a      macros and registers work
#   gd, K                  your LSP, if this project has one configured
#   :echo g:pystudio       true, so your config can detect pystudio
#   :echo g:pystudio_kernel  idle, busy, restarting or dead
#   ctrl+g z               zoom this pane, and again to restore
#
# When you are done: ctrl+g q. Neovim asks about unsaved buffers itself.
