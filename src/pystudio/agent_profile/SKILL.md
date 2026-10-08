---
name: data-science
description: How to do data science work inside pystudio, the terminal IDE this session runs in. Use it before writing or changing any analysis code here - exploratory analysis, cleaning, plots, statistics, regression, machine learning, Bayesian models and MCMC - and whenever the user asks about their data, their variables, a traceback in the console, or why a plot or table does not show.
---

# Data science in pystudio

You are in a column on the left of pystudio. To your right the user has a Neovim
editor, a console and a variable explorer attached to one Jupyter kernel, and a
plot pane. They read and run code there; you write it. This file is what makes
your code fit that setup.

## How the pieces behave

- **The script is made of cells.** A cell starts at a `# %%` line and runs to the
  next one. `# %% Fit the model` gives the cell a title.
- **The user runs the cells, not you.** They send a cell with `\c`, everything
  above the cursor with `\a`, the whole file with `\f`. `\a` and `\f` run cell
  by cell and stop at the first cell that raises. So never report a result you
  have not seen, and say which cell to run first.
- **Your edits are live.** The editor reloads a file the moment you write it,
  and each reload is one undo step for the user. Prefer a few deliberate edits
  to many small ones, since each is a separate undo.
- **State lives in the kernel.** Variables persist between cells and survive
  your edits. They are gone after a restart, which is why the file must rebuild
  them from top to bottom.
- **The plot pane shows PNG images only**, one figure at a time with a history
  the user pages through. It is roughly a third of the screen.
- **The variable explorer lists every variable** with its type and shape. The
  user can open any DataFrame, Series or array in a scrollable, sortable table.

## Look before you write

The `pystudio` MCP tools read the live kernel without running any cell:

- `list_variables` - what exists, with types and shapes.
- `inspect` - the repr of one expression: `df.dtypes`, `df.head()`,
  `df.isna().sum()`, `df["region"].value_counts()`, `model.summary()`.
- `read_console` - what the user's cells printed, and their tracebacks.

Use them before writing code about data. Real column names, dtypes and missing
values are the difference between code that runs and code that guesses. If the
data is only a path, read the head of the file. If the user says something
failed, read the console before proposing a fix; the traceback is there.

`inspect` evaluates in the user's live session. Use it only to look. Never use it
to assign, mutate, write files, install packages or start a long computation.

Do not run the user's script yourself in a shell to see what it does. It repeats
work their kernel has already done, may be slow or have side effects, and its
results are not the ones on their screen. The kernel is the source of truth.

## Writing cells

- Put imports in one cell at the top. Add to it rather than importing mid-file.
- One step per cell: load, clean, one summary, one plot, one model. A cell that
  does three things cannot be rerun for one of them.
- Give each cell a short title after `# %%`.
- Every cell must run on a fresh kernel when the cells above it have run, in
  order. That is what a replay with `\a` does after a restart.
- Make cells safe to run twice. Build `clean = raw.copy()` and work on the copy
  rather than modifying `raw` in place, so rerunning a cell does not apply a
  transformation again.
- End a cell with the expression worth seeing; its value prints in the console.
  Use `print` only when a cell shows more than one thing.
- Name results the user will want to open: `summary`, `by_region`, `residuals`.
  A named DataFrame is one keypress from the table viewer, which is better than
  printing 40 rows into the console.
- Put anything slow in its own cell: a large read, a grid search, MCMC sampling.
  The user can then rerun the cheap cells around it freely.
- Leave out `if __name__ == "__main__":` and wrapping everything in `main()`.
  Cell scripts are read and run top to bottom; a function is for logic used in
  more than one cell.
- Comment the choices, not the syntax: why rows are dropped, why a log scale.

## Plots

- matplotlib and seaborn work as they are. Call `plt.show()` at the end of the
  cell; each figure shown becomes one entry in the plot pane.
- One figure per cell. The pane shows one at a time, so several in a cell are
  easy to miss.
- Size for a small pane: around `figsize=(7, 4)`. Prefer two cells with one
  chart each over one figure with a 3 by 3 grid nobody can read at that size.
  Call `fig.tight_layout()`.
- Altair needs the PNG renderer, set once in the imports cell:
  `alt.renderers.enable("png", scale_factor=2)` (it uses `vl-convert-python`),
  and `alt.data_transformers.disable_max_rows()` for more than 5000 rows.
- Interactive output does not render: plotly figures, bokeh, ipywidgets, and
  HTML reprs appear as text or not at all. Export a static image instead, for
  plotly `fig.show(renderer="png")` with `kaleido` installed.
- Label axes with units and give each chart a title that says what it shows.

## Exploratory analysis

When asked for EDA without more detail, cover this, one cell each, and stop
short of modelling:

1. Load, then shape and `head()`.
2. Dtypes, missing values and number of unique values per column, as one table.
3. Fix what loading got wrong: dates parsed, numbers stored as text, obvious
   malformed rows. Say how many rows each fix touches.
4. Duplicates.
5. Numeric summary, then distributions. Use a log scale for heavily skewed
   columns and say that you did.
6. Categorical columns: counts for the top levels.
7. Relationships between the variables that matter for the user's question.
8. A short closing comment in the chat on what stands out and what you would
   check next. Leave conclusions to them.

## Models

- Regression and classical statistics: prefer `statsmodels` when the user wants
  to read coefficients and intervals, `scikit-learn` when they want prediction.
  Show the fit summary, then residual checks in their own cell.
- Machine learning: split before any fitting that learns from the data, put
  preprocessing in a `Pipeline` so it is fitted on the training part only, set
  `random_state`, and report a baseline next to the model.
- Bayesian models (PyMC, or what the file already uses):
  - State every prior in the code with a comment on why it is reasonable on the
    scale of the data. If the user gave priors, use exactly those.
  - Standardise predictors when priors are meant to be weakly informative, and
    say so.
  - Cells in this order: model definition, prior predictive check, sampling,
    diagnostics, posterior summary, posterior predictive check.
  - Sampling goes in its own cell with `random_seed` set, storing `idata`.
  - Diagnostics before interpretation: `az.summary` for `r_hat` and effective
    sample size, the count of divergences, and a trace plot. If they are bad,
    say so plainly instead of interpreting the posterior.

## Packages

The kernel runs in the project's environment, which may not have what you want
to import. Check with `inspect`, for example
`__import__("importlib.util").util.find_spec("pymc") is not None`. If something
is missing, tell the user the command (`uv add pymc`) rather than installing it
yourself, and prefer libraries the file already uses.

## When you finish

Tell the user in a few sentences what you added or changed, which cell to run
first, anything you assumed about the data, and anything you could not check
because it has not been run yet.
