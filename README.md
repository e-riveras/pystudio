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

Install the `pystudio` command straight from GitHub:

```sh
uv tool install git+https://github.com/e-riveras/pystudio    # or: pipx install git+https://github.com/e-riveras/pystudio
pystudio analysis.py
```

Each [release](https://github.com/e-riveras/pystudio/releases) also has a wheel
attached, which `uv tool install` or `pipx install` take as a path.

Options: `--clean` starts Neovim without your config, `--nvim PATH` picks a
different Neovim, `--python PATH` picks the kernel's interpreter, and
`--kernel NAME` uses a registered Jupyter kernel instead.

## Which Python runs your code

pystudio is installed in its own isolated environment, so the kernel looks for
your project's environment first. The first match wins:

1. `--python PATH`
2. `--kernel NAME`, a registered Jupyter kernel
3. the active virtualenv, `$VIRTUAL_ENV`
4. the nearest `.venv` in the opened file's directory or any parent
5. pystudio's own Python, which has none of your packages

The project's environment needs `ipykernel`. Without it pystudio falls back to
its own Python and says so in the console. Add it once per project:

```sh
uv add --dev ipykernel    # or: pip install ipykernel
```

The status bar shows which environment the kernel is running in.

Jupyter signs kernel messages but does not encrypt them, so pystudio starts its
kernel on Unix domain sockets in a directory only you can enter, not on TCP
ports. Nobody else on the machine can read your output, and nothing listens on
the network.

`ctrl+g k` changes it without leaving: it lists the project's environment, the
registered Jupyter kernels and the kernels already running on this machine.
Picking one of the first two starts a fresh kernel in place of the current one.
Picking a running kernel attaches to it, sharing its namespace with whatever
started it; pystudio can interrupt such a kernel but will not restart it, and
leaves it running on exit.

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

## The assistant

`ctrl+g a` swaps the console for a chat. Ask for code in plain words:

```
do some EDA on the csv I left at data/sales.csv
let's fit a linear model of price on area and rooms
build a Bayesian model for this with MCMC, normal priors on the slopes
```

The assistant reads the buffer, looks at the data it needs to, and writes the
code into the editor as `# %%` cells below the cell your cursor is in. It does
not run them: you do, with the same keys as any other cell. One request is one
undo step, so `u` in the editor takes back everything it just wrote. `escape`
at its prompt cancels a reply, and `ctrl+g 2` brings the console back.

To write code that fits your data it may look before it writes: list the
kernel's variables, evaluate an expression such as `df.dtypes` or `df.head()`,
read the first lines of a file, or read the end of the console after an error.
Each of these shows up in the chat as it happens. Inspection is kept out of the
console and the history, but it is an expression evaluated in your live
session, not a sandbox, so the chat is where to see what was asked.

It needs credentials for Anthropic's API: set `ANTHROPIC_API_KEY`, or run
`ant auth login`. Without them pystudio works as before and the chat says what
is missing. The model is Claude Sonnet 5.5; `PYSTUDIO_ASSISTANT_MODEL` picks
another. Requests are billed to your account.

What leaves your machine: your request, the buffer's text, and whatever the
assistant inspects, meaning variable names with short previews, the output of
the expressions it evaluates, file heads and console text. Nothing is sent
until you ask it something.

The model sits behind a small interface (`pystudio/assistant/provider.py`), so
another provider is one module and one entry in `PROVIDERS`, selected with
`PYSTUDIO_ASSISTANT`. Only Anthropic is implemented.

## Keys

Neovim owns its whole keyspace, so pystudio's own keys sit behind a `ctrl+g`
chord. Press `ctrl+g`, then:

| Key | Action |
| --- | --- |
| `1` `2` `3` `4` | focus editor, console, variables, plots |
| `a` | show the assistant in the console's place; `2` brings the console back |
| `z` | zoom the focused pane, toggle |
| `r` | restart the kernel |
| `i` | interrupt the kernel |
| `k` | pick another kernel |
| `q` | quit (Neovim prompts about unsaved buffers) |
| `escape` | cancel the chord |

Inside the editor, under `<localleader>` (`\` unless you set one):

| Key | Action |
| --- | --- |
| `l` | send the current line, or the visual selection, and advance past it |
| `c` | send the current `# %%` cell, then move to the next one |
| `f` | send the whole buffer, cell by cell |
| `a` | send every cell above this one, to replay state after a restart |
| `e` | send from the cursor to the end of the buffer |
| `.` | send the last thing again |

`f` and `a` send one cell at a time, wait for each to finish, and stop at the
first one that fails, saying in the console which cell stopped them. A typo or
an exception halfway down therefore costs you only the cells after it. Cells
with nothing but comments are skipped.

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
- **Assistant.** A loop in `pystudio/assistant/agent.py` sends the request to a
  provider and runs the tools the model calls: reading the buffer and writing
  to it over the Neovim RPC channel, and inspecting the kernel with the same
  quiet expressions the variable explorer uses. No widget is imported there;
  the app hands it a workspace.
- **Cursor.** A character cell cannot be subdivided, so a block cursor is drawn
  reversed, a horizontal one underlines its character, and a vertical one becomes
  a thin bar glyph in place of the character.

## Development

```sh
just install  # put an editable `pystudio` on PATH, tracking this checkout
just run analysis.py    # or run it from the checkout without installing
just test     # or: uv run pytest
just lint
just fmt
```

To release, set the version in `pyproject.toml`, date its entry in
`CHANGELOG.md`, commit, then run `just release`. It lints, tests, builds, tags
`v<version>`, pushes the tag and creates a GitHub release with the sdist and
wheel attached, using the changelog entry as the notes. Publishing to PyPI is a
separate step, `just publish`.

The kernel and Neovim layers are covered by integration tests that drive a real
kernel and a real `nvim --clean --embed`; the app tests drive the whole UI
headless through Textual's pilot.

## Not in this version

Notebook (`.ipynb`) editing, inline images in the editor buffer, and
`ext_multigrid` (Neovim's own splits as separate panes).

## License

MIT. See [LICENSE](LICENSE).
