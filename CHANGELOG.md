# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `pystudio --version`.

### Fixed

- `pystudio --demo` after a plain install now says the tour needs numpy, pandas
  and matplotlib and how to install them, instead of starting and failing at
  the first import. The check used to run only for a project environment.
- Quitting while the kernel is still starting no longer ends in a traceback.
- Closing the agent pane no longer fails on macOS when its program has already
  exited.

## [0.2.0] - 2026-10-08

### Added

- `pystudio --demo` opens the guided tour, which now comes with the install.
  The `[demo]` extra installs what it imports.
- The plot pane zooms and pans, by key and with the mouse, and `f` or a double
  click fills the screen with it.
- matplotlib figures are drawn at the pane's resolution, and drawn again by the
  kernel on zoom, pan and resize, so a zoomed plot gains detail. `a` lays the
  figure out for the pane instead of keeping the size it was made at.
- Panes resize: `ctrl+g` then `<` `>` `+` `-`, or drag a border. `ctrl+g p`
  switches between three layouts.
- A plot gallery on `g`, with delete; `o` opens a figure outside pystudio, `y`
  copies it, and `S` and `P` save it as SVG and PDF.
- Plotly figures and Altair charts get an entry in the plot history that opens
  in the browser.
- The kernel runs in your project's environment: `$VIRTUAL_ENV`, or the nearest
  `.venv` above the opened file, when it has `ipykernel`. Otherwise pystudio
  falls back to its own Python and says how to fix it. The status bar names
  the environment.
- `--python PATH` picks the kernel's interpreter explicitly.
- Both AI features below are optional and off by default. Install them with the
  `[assistant]`, `[agent]` or `[ai]` extra and turn them on with `--assistant`
  and `--agent`, or `PYSTUDIO_ASSISTANT` and `PYSTUDIO_AGENT`.
- An agent pane, on `ctrl+g c`: a full-height column running Claude Code's own
  CLI in an embedded terminal, with your existing login. Its edits appear live
  in the editor, and it can inspect the kernel through an MCP server.
- The agent starts with a `pystudio:data-science` skill: the conventions for
  cells, the kernel tools, plots and modelling workflows inside pystudio.
- Buffers reload as soon as their file changes on disk, as one undo step;
  unsaved edits are kept.
- An assistant, on `ctrl+g a`: ask for analysis code in plain words and it
  writes `# %%` cells into the editor, after looking at the buffer, the
  kernel's variables and the files it needs. It never runs the code. Uses
  Anthropic's API and needs `ANTHROPIC_API_KEY` or `ant auth login`.
- `ctrl+g k` opens a kernel picker: switch to the project's environment or a
  registered Jupyter kernel, or attach to a kernel that is already running.

### Changed

- The assistant and the agent plot with Altair by default, and fall back to
  matplotlib when the file already uses it or Altair cannot draw the chart.

- Sending the whole file (`\f`) or everything above (`\a`) runs one cell at a
  time and stops at the first that fails, instead of sending one block that a
  single error or typo stopped as a whole.
- The kernel listens on Unix domain sockets in a private directory instead of
  unencrypted TCP ports on loopback.
- `--kernel` no longer defaults to `python3`; naming a kernel now turns off
  environment detection.

### Fixed

- Starting without a file no longer shows Neovim's intro screen.
- A kernel that fails to start is cleaned up instead of left running.
- `ctrl+g` shortcuts work while typing in the console prompt; the second key
  used to be typed into the prompt instead.
- The kernel no longer stops answering after a request reached it while a cell
  was running. Requests are now sent one at a time.

## [0.1.0] - 2026-10-01

First release, on GitHub.

### Added

- Four-pane layout: an embedded Neovim editor, a console, a variable explorer
  and a plot pane, all on one Jupyter kernel.
- The editor is your own `nvim --embed`, attached as a UI, so your config,
  plugins and LSP work unchanged. The cursor follows Neovim's mode.
- Sending lines, selections and `# %%` cells from the editor to the kernel.
- A variable explorer, and a paged table viewer for data frames.
- Plots rendered with Kitty graphics or Sixel, falling back to half-cell blocks,
  with a history to page through.
- Console completion, history, `input()` support, interrupt, restart and replay.
- A guided tour in `examples/demo.py`, run by the test suite.
- A startup check that Neovim 0.10 or newer is on `PATH`.

[Unreleased]: https://github.com/e-riveras/pystudio/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/e-riveras/pystudio/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/e-riveras/pystudio/releases/tag/v0.1.0
