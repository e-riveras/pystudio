"""Which Python the kernel runs in.

Installed as a tool, pystudio lives in its own isolated environment, which has
none of the user's packages. So the kernel prefers the project's environment,
and only falls back to pystudio's own Python, through the ``python3``
kernelspec, when there is no usable one. The first match wins:

1. ``--python PATH``, which must have ipykernel.
2. ``--kernel NAME``, a registered kernelspec, used as is.
3. ``$VIRTUAL_ENV``.
4. The nearest ``.venv`` at or above the opened file's directory.
5. pystudio's own Python.

A project environment without ipykernel falls through to 5 with a note saying
how to add it, rather than starting a kernel that cannot run.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KERNEL = "python3"
IPYKERNEL_TIMEOUT = 30.0


class InterpreterError(Exception):
    """An explicitly requested interpreter cannot run a kernel."""


@dataclass(frozen=True)
class KernelChoice:
    """How to start the kernel, and how to describe it to the user."""

    kernel_name: str = DEFAULT_KERNEL
    python: Path | None = None
    label: str = DEFAULT_KERNEL
    note: str | None = None


def env_python(env_dir: Path) -> Path:
    return env_dir / "bin" / "python"


def find_project_python(
    start: Path, env: Mapping[str, str] | None = None
) -> tuple[Path, str] | None:
    """The project's interpreter and a short label for it, or None."""
    env = os.environ if env is None else env
    virtual_env = env.get("VIRTUAL_ENV")
    if virtual_env:
        python = env_python(Path(virtual_env))
        if python.exists():
            return python, Path(virtual_env).name
    for directory in (start, *start.parents):
        python = env_python(directory / ".venv")
        if python.exists():
            return python, ".venv"
    return None


def has_ipykernel(python: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", "import ipykernel"],
            capture_output=True,
            timeout=IPYKERNEL_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def resolve(
    *,
    python: Path | None = None,
    kernel_name: str | None = None,
    start: Path,
    env: Mapping[str, str] | None = None,
) -> KernelChoice:
    """Pick the kernel's interpreter. Raises :class:`InterpreterError`."""
    if python is not None:
        if not has_ipykernel(python):
            raise InterpreterError(
                f"{python} cannot import ipykernel; "
                f"install it with: uv pip install --python {python} ipykernel"
            )
        return KernelChoice(python=python, label=python.parent.parent.name or str(python))
    if kernel_name is not None:
        return KernelChoice(kernel_name=kernel_name, label=kernel_name)

    found = find_project_python(start.resolve(), env)
    if found is None:
        return KernelChoice()
    project_python, label = found
    if has_ipykernel(project_python):
        return KernelChoice(python=project_python, label=label)
    return KernelChoice(
        note=f"{label} has no ipykernel, so the kernel runs in pystudio's own Python "
        "without your project's packages. Add it with: uv add --dev ipykernel"
    )
