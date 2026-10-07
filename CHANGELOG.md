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
- `ctrl+g k` opens a kernel picker: switch to the project's environment or a
  registered Jupyter kernel, or attach to a kernel that is already running.

### Changed

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
