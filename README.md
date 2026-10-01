# pystudio

A terminal IDE for Python data science: a mix of RStudio and Jupyter, with a real
Neovim as the editor.

```
┌ editor (nvim) ────────────┬ variables ─────────┐
│ df = pd.read_csv("a.csv") │ df  DataFrame      │
│ df.head()                 │     (1000, 12)     │
├ console ──────────────────┼ plots ─────────────┤
│ In [1]: df.head()         │  ▁▂▄▆█▆▄▂▁  3/7    │
└───────────────────────────┴────────────────────┘
 kernel: idle · python3 · analysis.py · tgp
```

Four panes, one Jupyter kernel, one screen. Works over SSH, no browser.

The editor is not a reimplementation. pystudio spawns `nvim --embed` and attaches
to it as a UI, so your `init.lua`, plugins, LSP, treesitter, macros and registers
all behave exactly as they do in your daily editor. Send a line to the kernel and
the result appears in the console, the variable explorer updates, and figures
land in the plot pane.

## Requirements

- Python 3.12 or newer
- Neovim 0.10 or newer on `PATH`
- A terminal with Kitty graphics or Sixel for real plots (Kitty, Ghostty,
  WezTerm, iTerm2). Everything else falls back to half-cell blocks, and the
  status bar names the protocol in use.

## Install and run

pystudio is published on PyPI as `pystudio-tui`; the command it installs is
`pystudio`.

```sh
uv tool install pystudio-tui    # or: pipx install pystudio-tui
pystudio analysis.py
```

From a checkout:

```sh
uv sync
uv run pystudio analysis.py
```

Options: `--clean` starts Neovim without your config, `--nvim PATH` picks a
different Neovim, `--kernel NAME` picks a different Jupyter kernel.

## The guided tour

```sh
just demo
```

[`examples/demo.py`](examples/demo.py) walks through every feature in fourteen
cells, each one saying which key to press and what should happen: sending lines
and cells, the variable explorer, the table viewer and its paging, plots and
their history, completion at the prompt, tracebacks, interrupting, restarting
and replaying, and proving the editor really is your Neovim. A test runs all of
it, so the tour cannot drift away from the code.

## Keys

Neovim owns its whole keyspace, so pystudio's own keys sit behind a `ctrl+g`
chord. Press `ctrl+g`, then:

| Key | Action |
| --- | --- |
| `1` `2` `3` `4` | focus editor, console, variables, plots |
| `z` | zoom the focused pane, toggle |
| `r` | restart the kernel |
| `i` | interrupt the kernel |
| `q` | quit (Neovim prompts about unsaved buffers) |
| `escape` | cancel the chord |

Inside the editor, under `<localleader>` (`\` unless you set one):

| Key | Action |
| --- | --- |
| `l` | send the current line, or the visual selection, and advance past it |
| `c` | send the current `# %%` cell, then move to the next one |
| `f` | send the whole buffer |
| `a` | send everything above this cell, to replay state after a restart |
| `e` | send from the cursor to the end of the buffer |
| `.` | send the last thing again |

If you use a separate `<leader>`, the same six keys are offered there too, so
`<space>c` works as well as `\c`. A key is skipped when it would collide with a
mapping you already have — including as a prefix, so pystudio will not take
`<leader>f` out from under your own `<leader>ff`. What it mapped and what it
skipped are in `g:pystudio_keys` and `g:pystudio_keys_skipped`.

The same actions are available as `:PyStudioSend`, `:PyStudioSendCell`,
`:PyStudioSendFile`, `:PyStudioSendAbove`, `:PyStudioSendToEnd`,
`:PyStudioSendLast`, `:PyStudioInterrupt` and `:PyStudioRestart`. `<C-CR>` is
bound to send-line too, for terminals that can tell it apart from `Enter`.

Cells are drawn: a rule above each marker, and a faint wash over the cell the
cursor is in, so what `c` will send is visible before you press it. Both come
from the `PyStudioCellBorder` and `PyStudioCell` highlight groups, which link to
`Comment` and `CursorLine` by default and can be overridden in your config.

At the console prompt, `Tab` completes through the kernel, `up` and `down` walk
the history, and an empty line ends an unfinished block.

In the plot pane, `[` and `]` step through the history and `ctrl+s` saves the
current figure.

In the variables pane, `enter` opens a DataFrame, Series or array in a scrollable
table, and prints anything else to the console. In that table, `s` sorts by the
column under the cursor (pressing it again reverses), clicking a header does the
same, and `escape` closes it. Rows are fetched a page at a time and sorting
happens in the kernel, so a million-row frame opens as fast as a small one.

Your Neovim can see pystudio: `vim.g.pystudio` is true, and
`vim.g.pystudio_kernel` holds `idle`, `busy`, `restarting` or `dead` for a
statusline.

## How it works

```
                pystudio (Textual, owns the screen)
  ┌────────────────────────────┬──────────────────────┐
  │ NvimPane                   │ VariablesPane        │
  │   msgpack-RPC over stdio   │                      │
  │   ├─ redraw  -> Rich cells ├──────────────────────┤
  │   ├─ keys    -> nvim_input │ PlotsPane            │
  │   └─ notify  <- send.lua   │                      │
  ├────────────────────────────┴──────────────────────┤
  │ ConsolePane                                       │
  └───────────────────────────────────────────────────┘
        │                                │
        │ nvim --embed analysis.py       │ display_data PNG
        └── KernelSession ──ZMQ── ipykernel subprocess
```

- **Editor.** `nvim_ui_attach` with `ext_linegrid` only, so Neovim draws its own
  command line, popup menu, messages and tabline as ordinary cells. The grid
  model is plain data (`pystudio/nvim/grid.py`) and the pane turns each row into
  Rich segments.
- **Send path.** `pystudio/lua/send.lua` is injected after attach and notifies
  pystudio over the same RPC channel that carries redraws back. No temp files, no
  clipboard, no pseudo-terminal. `pystudio/lua/cells.lua` draws the cell
  decoration with extmarks, in two namespaces: the rules only change when the
  text does, the wash follows the cursor.
- **Variables.** Snapshots are taken with an `execute_request` that has empty
  code and asks for `__pystudio_inspect__()` in `user_expressions`, so nothing is
  added to the kernel's history and nothing is published for the console to
  print.
- **Plots.** `image/png` from `display_data` goes to the plot pane, rendered by
  `textual-image` with whatever protocol the terminal supports.
- **Table viewer.** The same quiet-expression trick fetches one page of rows at a
  time, so nothing is loaded that is not on screen.
- **Cursor.** A character cell cannot be subdivided, so a block cursor is drawn
  reversed, a horizontal one underlines its character, and a vertical one becomes
  a thin bar glyph in place of the character.

## Development

```sh
just test     # or: uv run pytest
just lint
just fmt
```

To release, set the version in `pyproject.toml`, date its entry in
`CHANGELOG.md`, commit, then run `just release` with a PyPI token in
`UV_PUBLISH_TOKEN`. It lints, tests, builds, tags `v<version>`, publishes and
pushes the tag.

The kernel and Neovim layers are covered by integration tests that drive a real
kernel and a real `nvim --clean --embed`; the app tests drive the whole UI
headless through Textual's pilot.

## Not in this version

Notebook (`.ipynb`) editing, inline images in the editor buffer, `ext_multigrid`
(Neovim's own splits as separate panes), and choosing or reconnecting to a kernel
after startup.

## License

MIT. See [LICENSE](LICENSE).
