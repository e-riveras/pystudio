"""Command line entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


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
