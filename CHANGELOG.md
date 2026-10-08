# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The kernel runs in your project's environment: `$VIRTUAL_ENV`, or the nearest
  `.venv` above the opened file, when it has `ipykernel`. Otherwise pystudio
  falls back to its own Python and says how to fix it. The status bar names
  the environment.
- `--python PATH` picks the kernel's interpreter explicitly.
- An agent pane, on `ctrl+g c`: a full-height column running Claude Code's own
  CLI in an embedded terminal, with your existing login. Its edits appear live
  in the editor, and it can inspect the kernel through an MCP server.
- Buffers reload as soon as their file changes on disk, as one undo step;
  unsaved edits are kept.
- An assistant, on `ctrl+g a`: ask for analysis code in plain words and it
  writes `# %%` cells into the editor, after looking at the buffer, the
  kernel's variables and the files it needs. It never runs the code. Uses
  Anthropic's API and needs `ANTHROPIC_API_KEY` or `ant auth login`.
- `ctrl+g k` opens a kernel picker: switch to the project's environment or a
  registered Jupyter kernel, or attach to a kernel that is already running.

### Changed

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

[Unreleased]: https://github.com/e-riveras/pystudio/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/e-riveras/pystudio/releases/tag/v0.1.0
