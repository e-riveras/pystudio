# pystudio tasks

default: test

# Run the app; pass a file, e.g. `just run analysis.py`
run *ARGS:
    uv run pystudio {{ARGS}}

test *ARGS:
    uv run pytest {{ARGS}}

# The guided tour
demo:
    uv run pystudio examples/demo.py

# Fast tests only: no kernel, no Neovim
unit:
    uv run pytest tests/test_grid.py tests/test_keys.py -q

lint:
    uv run ruff check src tests
    uv run ruff format --check src tests

fmt:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# Textual's console, for debugging the UI in a second terminal
console:
    uv run textual console
