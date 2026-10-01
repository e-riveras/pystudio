"""Command line entry point."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_NVIM = (0, 10)


def nvim_version(nvim: str) -> tuple[int, int] | None:
    """Major and minor of ``nvim --version``, or None if it cannot be read."""
    try:
        out = subprocess.run([nvim, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"NVIM v(\d+)\.(\d+)", out)
    return (int(match[1]), int(match[2])) if match else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystudio",
        description="A terminal IDE for Python data science: Neovim, a Jupyter kernel, "
        "variables and plots in one screen.",
    )
    parser.add_argument("file", nargs="?", type=Path, help="script to open in the editor")
    parser.add_argument("--clean", action="store_true", help="start Neovim without your own config")
    parser.add_argument("--nvim", default="nvim", help="path to the Neovim executable")
    parser.add_argument("--kernel", default="python3", help="Jupyter kernel name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if shutil.which(args.nvim) is None:
        print(f"pystudio: cannot find {args.nvim!r} on PATH", file=sys.stderr)
        return 1
    version = nvim_version(args.nvim)
    if version is not None and version < MIN_NVIM:
        need = ".".join(map(str, MIN_NVIM))
        have = ".".join(map(str, version))
        print(f"pystudio: needs Neovim {need} or newer, found {have}", file=sys.stderr)
        return 1

    from pystudio.app import PyStudioApp

    app = PyStudioApp(
        path=args.file,
        clean=args.clean,
        nvim=args.nvim,
        kernel_name=args.kernel,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
