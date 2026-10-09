# Contributing to pystudio

Bug reports, ideas and pull requests are welcome. pystudio is a side project in
an early state, so answers may take a few days.

## Reporting a bug

Open an [issue](https://github.com/e-riveras/pystudio/issues) and say:

- what you did, what you expected and what happened instead
- your terminal (Kitty, Ghostty, WezTerm, iTerm2, ...) and operating system
- the output of `pystudio --version`, `nvim --version | head -1` and
  `python --version`
- whether it also happens with `pystudio --clean`, which starts Neovim without
  your own config

A traceback, if there is one, helps more than anything else.

## Setting up

You need [uv](https://docs.astral.sh/uv/), [just](https://just.systems) and
Neovim 0.10 or newer on `PATH`.

```sh
git clone https://github.com/e-riveras/pystudio
cd pystudio
just run analysis.py   # run from the checkout
just install           # or put an editable `pystudio` on PATH
```

`uv` creates the environment on first use. Nothing else needs installing.

## Before you open a pull request

```sh
just fmt     # format and apply the safe lint fixes
just lint    # what CI checks
just test    # the whole suite, about a minute and a half
just unit    # the fast tests only: no kernel, no Neovim
```

CI runs lint, the tests on Linux and macOS with Python 3.12 to 3.14, and a
build. A pull request needs it green.

Most tests drive a real kernel and a real `nvim --embed`, and the app tests run
the whole UI headless through Textual's pilot. A change in behaviour should
come with a test that fails without it.

## What a change should look like

- One change per pull request. A fix and an unrelated cleanup are two.
- Commit subjects follow [Conventional Commits](https://www.conventionalcommits.org):
  `feat:`, `fix:`, `docs:`, `chore:`. The body says why, not what.
- Anything a user would notice gets a line under `## [Unreleased]` in
  `CHANGELOG.md`.
- Keys and features a user meets are shown in the guided tour,
  `src/pystudio/examples/demo.py`, which a test runs cell by cell.
- Match the code around you: docstrings that say what a thing is for, comments
  for the choices that are not obvious, no comment that repeats the code.

For anything larger than a fix, open an issue first so the approach can be
agreed before you write it.

## How the code is laid out

The "How it works" section of the [README](README.md#how-it-works) maps the
panes to the modules behind them. In short: `kernel.py` and `nvim/` are plain
asyncio and import no widget, `widgets/` are the panes, and `app.py` wires them
together.

## License

pystudio is MIT licensed, and contributions are accepted under the same terms.
