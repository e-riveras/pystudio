# pystudio tasks

default: test

# Run the app; pass a file, e.g. `just run analysis.py`
run *ARGS:
    uv run pystudio {{ARGS}}

# Install an editable `pystudio` command on PATH that tracks this checkout
install:
    uv tool install --editable . --force

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

# Build the sdist and wheel into dist/
build:
    rm -rf dist
    uv build

# Check, build, tag and publish a GitHub release with the sdist and wheel attached
release: lint test build
    #!/usr/bin/env sh
    set -eu
    version=$(uv version --short)
    if [ -n "$(git status --porcelain)" ]; then
        echo "working tree is not clean" >&2
        exit 1
    fi
    if grep -q "## \[$version\] - Unreleased" CHANGELOG.md; then
        echo "CHANGELOG.md still marks $version as Unreleased" >&2
        exit 1
    fi
    notes=$(mktemp)
    awk -v v="$version" '$0 ~ "^## \\[" v "\\]" {on=1; next} /^## \[/ {on=0} /^\[/ {on=0} on' CHANGELOG.md > "$notes"
    git tag -a "v$version" -m "v$version"
    git push origin "v$version"
    gh release create "v$version" dist/* --title "v$version" --notes-file "$notes"
    rm -f "$notes"

# Upload the built dist/ to PyPI; needs a token in UV_PUBLISH_TOKEN
publish: build
    uv publish
