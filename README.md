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

```sh
uv sync
uv run pystudio analysis.py
```

Options: `--clean` starts Neovim without your config, `--nvim PATH` picks a
different Neovim, `--kernel NAME` picks a different Jupyter kernel.

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

Inside the editor, with `<localleader>` (`\` unless you set one):

| Key | Action |
| --- | --- |
| `<localleader>l` | send the current line, or the visual selection, and advance |
| `<localleader>c` | send the current `# %%` cell |
| `<localleader>f` | send the whole buffer |

The same actions are available as `:PyStudioSend`, `:PyStudioSendCell`,
`:PyStudioSendFile`, `:PyStudioInterrupt` and `:PyStudioRestart`. `<C-CR>` is
bound to send-line too, for terminals that can tell it apart from `Enter`.

In the plot pane, `[` and `]` step through the history and `ctrl+s` saves the
current figure. In the variables pane, `enter` shows a value in the console.

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
  clipboard, no pseudo-terminal.
- **Variables.** Snapshots are taken with an `execute_request` that has empty
  code and asks for `__pystudio_inspect__()` in `user_expressions`, so nothing is
  added to the kernel's history and nothing is published for the console to
  print.
- **Plots.** `image/png` from `display_data` goes to the plot pane, rendered by
  `textual-image` with whatever protocol the terminal supports.

## Development

```sh
just test     # or: uv run pytest
just lint
just fmt
```

The kernel and Neovim layers are covered by integration tests that drive a real
kernel and a real `nvim --clean --embed`; the app tests drive the whole UI
headless through Textual's pilot.

## Not in this version

Notebook (`.ipynb`) editing, a sortable DataFrame viewer, completion in the
console, and inline images in the editor buffer.
