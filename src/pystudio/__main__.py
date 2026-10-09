"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pystudio.interpreter import KernelChoice

MIN_NVIM = (0, 10)

DEMO_NAME = "pystudio_demo.py"
DEMO_NEEDS = ("numpy", "pandas", "matplotlib")
"""What the guided tour imports, which the kernel's interpreter has to have."""


def write_demo(directory: Path) -> Path:
    """Put the guided tour in ``directory``, keeping a copy that is already there."""
    from importlib.resources import files

    target = directory / DEMO_NAME
    if not target.exists():
        source = files("pystudio").joinpath("examples", "demo.py")
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def demo_problem(python: Path) -> str | None:
    """What the tour is missing in the kernel's interpreter, or None when it is all there."""
    check = "; ".join(f"import {module}" for module in DEMO_NEEDS)
    try:
        done = subprocess.run([str(python), "-c", check], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 0:
        return None
    return (
        f"the tour needs {', '.join(DEMO_NEEDS)}, and {python} lacks some of them. "
        "Run it from a project that has them, or install pystudio with them: "
        'uv tool install "pystudio-tui[demo] @ git+https://github.com/e-riveras/pystudio"'
    )


def kernel_python(choice: KernelChoice) -> Path | None:
    """The interpreter ``choice`` runs, or None when its kernelspec does not say.

    Without a project environment the kernel comes from a kernelspec, whose
    first argument is the interpreter. That is the case right after a plain
    install, the one most likely to lack what the tour imports. jupyter_client
    runs a bare ``python`` there as the Python it is running in itself, not as
    whatever ``python`` is on PATH, and so does this.
    """
    if choice.python is not None:
        return choice.python
    from jupyter_client.kernelspec import KernelSpecManager, NoSuchKernel

    try:
        spec = KernelSpecManager().get_kernel_spec(choice.kernel_name)
    except NoSuchKernel:
        return None
    if spec.language != "python" or not spec.argv:
        return None
    major, minor = sys.version_info[:2]
    if spec.argv[0] in {"python", f"python{major}", f"python{major}.{minor}"}:
        return Path(sys.executable)
    found = shutil.which(spec.argv[0])
    return Path(found) if found is not None else None


def nvim_version(nvim: str) -> tuple[int, int] | None:
    """Major and minor of ``nvim --version``, or None if it cannot be read."""
    try:
        out = subprocess.run([nvim, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"NVIM v(\d+)\.(\d+)", out)
    return (int(match[1]), int(match[2])) if match else None


def installed_version() -> str:
    """The version of the installed distribution, which is what a bug report needs."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("pystudio-tui")
    except PackageNotFoundError:
        from pystudio import __version__

        return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystudio",
        description="A terminal IDE for Python data science: Neovim, a Jupyter kernel, "
        "variables and plots in one screen.",
    )
    parser.add_argument("file", nargs="?", type=Path, help="script to open in the editor")
    parser.add_argument("--version", action="version", version=f"pystudio {installed_version()}")
    parser.add_argument(
        "--demo",
        action="store_true",
        help=f"open the guided tour, a copy of which is written to ./{DEMO_NAME}",
    )
    parser.add_argument("--clean", action="store_true", help="start Neovim without your own config")
    parser.add_argument("--nvim", default="nvim", help="path to the Neovim executable")
    parser.add_argument(
        "--python",
        type=Path,
        help="interpreter for the kernel (default: $VIRTUAL_ENV, then the nearest .venv)",
    )
    parser.add_argument(
        "--kernel", help="registered Jupyter kernel to use instead of a project interpreter"
    )
    from pystudio.agents import DEFAULT_AGENT
    from pystudio.assistant.provider import DEFAULT_PROVIDER

    ai = parser.add_argument_group(
        "AI features", "Both are off unless asked for here or in the environment."
    )
    ai.add_argument(
        "--assistant",
        nargs="?",
        const=DEFAULT_PROVIDER,
        metavar="PROVIDER",
        help="turn on the ctrl+g a assistant, which writes cells through an API "
        f"(default provider: {DEFAULT_PROVIDER}; or set $PYSTUDIO_ASSISTANT)",
    )
    ai.add_argument(
        "--agent",
        nargs="?",
        const=DEFAULT_AGENT,
        metavar="NAME",
        help="turn on the ctrl+g c pane, which runs a coding agent's own CLI "
        f"(default agent: {DEFAULT_AGENT}; or set $PYSTUDIO_AGENT)",
    )
    return parser


EXTRAS = {
    "assistant": ("anthropic",),
    "agent": ("pyte", "mcp"),
}
"""The optional dependencies each AI feature needs, by the name of its extra."""


def missing_extra(feature: str) -> str | None:
    """How to install what ``feature`` needs, or None when it is all there."""
    from importlib.util import find_spec

    if all(find_spec(module) is not None for module in EXTRAS[feature]):
        return None
    return (
        f"--{feature} needs the {feature!r} extra: "
        f'uv tool install "pystudio-tui[{feature}] @ git+https://github.com/e-riveras/pystudio"'
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from pystudio.agents import AGENT_VARIABLE, AGENTS, DEFAULT_AGENT
    from pystudio.assistant.provider import DEFAULT_PROVIDER, PROVIDER_VARIABLE, PROVIDERS

    # `pystudio --agent analysis.py` reads the file as the flag's optional
    # value; hand it back when it is not a name the flag knows.
    for flag, known, default in (
        ("assistant", PROVIDERS, DEFAULT_PROVIDER),
        ("agent", AGENTS, DEFAULT_AGENT),
    ):
        value = getattr(args, flag)
        if value is not None and value not in known and args.file is None:
            args.file = Path(value)
            setattr(args, flag, default)

    features = {
        "assistant": (args.assistant or os.environ.get(PROVIDER_VARIABLE) or None, PROVIDERS),
        "agent": (args.agent or os.environ.get(AGENT_VARIABLE) or None, AGENTS),
    }
    for feature, (name, known) in features.items():
        if name is None:
            continue
        if name not in known:
            names = ", ".join(sorted(known))
            print(f"pystudio: unknown {feature} {name!r}; known: {names}", file=sys.stderr)
            return 1
        problem = missing_extra(feature)
        if problem is not None:
            print(f"pystudio: {problem}", file=sys.stderr)
            return 1

    if shutil.which(args.nvim) is None:
        print(f"pystudio: cannot find {args.nvim!r} on PATH", file=sys.stderr)
        return 1
    version = nvim_version(args.nvim)
    if version is not None and version < MIN_NVIM:
        need = ".".join(map(str, MIN_NVIM))
        have = ".".join(map(str, version))
        print(f"pystudio: needs Neovim {need} or newer, found {have}", file=sys.stderr)
        return 1

    from pystudio.interpreter import InterpreterError, resolve

    if args.demo:
        if args.file is not None:
            print("pystudio: --demo opens the tour, so it takes no file", file=sys.stderr)
            return 1
        args.file = write_demo(Path.cwd())

    start = args.file.parent if args.file is not None else Path.cwd()
    try:
        choice = resolve(python=args.python, kernel_name=args.kernel, start=start)
    except InterpreterError as error:
        print(f"pystudio: {error}", file=sys.stderr)
        return 1

    python = kernel_python(choice) if args.demo else None
    if python is not None:
        problem = demo_problem(python)
        if problem is not None:
            print(f"pystudio: {problem}", file=sys.stderr)
            return 1

    from pystudio.app import PyStudioApp

    app = PyStudioApp(
        path=args.file,
        clean=args.clean,
        nvim=args.nvim,
        choice=choice,
        assistant=features["assistant"][0],
        agent=features["agent"][0],
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
