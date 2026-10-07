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

After startup the same sources, plus the kernels already running on this
machine, are offered by :func:`candidates` for the kernel picker.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KERNEL = "python3"
IPYKERNEL_TIMEOUT = 30.0
PORT_TIMEOUT = 0.2


class InterpreterError(Exception):
    """An explicitly requested interpreter cannot run a kernel."""


@dataclass(frozen=True)
class KernelChoice:
    """How to start the kernel, and how to describe it to the user."""

    kernel_name: str = DEFAULT_KERNEL
    python: Path | None = None
    label: str = DEFAULT_KERNEL
    note: str | None = None
    connection_file: Path | None = None
    """Set to attach to a kernel that is already running instead of starting one."""

    @property
    def target(self) -> tuple[str, Path | None, Path | None]:
        """What the kernel is, apart from how it is described."""
        return self.kernel_name, self.python, self.connection_file

    @property
    def detail(self) -> str:
        """One line saying where the kernel comes from, for the picker."""
        if self.connection_file is not None:
            return f"running · {self.connection_file.name}"
        if self.python is not None:
            return str(self.python)
        return "registered kernel"


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


def running_kernels(runtime_dir: Path, exclude: Path | None = None) -> list[Path]:
    """Connection files in ``runtime_dir`` whose kernel still answers on its shell socket.

    Kernels that crash leave their connection file behind, so the file alone
    proves nothing.
    """
    alive = []
    for path in sorted(runtime_dir.glob("kernel-*.json")):
        if exclude is not None and path == exclude:
            continue
        try:
            info = json.loads(path.read_text())
            ip, port = str(info["ip"]), int(info["shell_port"])
            if info.get("transport", "tcp") == "ipc":
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(PORT_TIMEOUT)
                    probe.connect(f"{ip}-{port}")
            else:
                socket.create_connection((ip, port), timeout=PORT_TIMEOUT).close()
            alive.append(path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return alive


def candidates(
    *,
    start: Path,
    env: Mapping[str, str] | None = None,
    kernel_names: list[str] | None = None,
    runtime_dir: Path | None = None,
    exclude: Path | None = None,
) -> list[KernelChoice]:
    """Every kernel worth offering: the project's, the registered, the running.

    The project environment is listed without checking it for ipykernel, which
    costs a subprocess; whoever starts it checks then.
    """
    if kernel_names is None:
        from jupyter_client.kernelspec import KernelSpecManager

        kernel_names = sorted(KernelSpecManager().find_kernel_specs())
    if runtime_dir is None:
        from jupyter_core.paths import jupyter_runtime_dir

        runtime_dir = Path(jupyter_runtime_dir())

    choices = []
    found = find_project_python(start.resolve(), env)
    if found is not None:
        choices.append(KernelChoice(python=found[0], label=found[1]))
    choices.extend(KernelChoice(kernel_name=name, label=name) for name in kernel_names)
    choices.extend(
        KernelChoice(connection_file=path, label=path.stem.removeprefix("kernel-")[:8])
        for path in running_kernels(runtime_dir, exclude)
    )
    return choices
