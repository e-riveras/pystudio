from __future__ import annotations

import json
import socket
import stat
from pathlib import Path

import pytest

from pystudio.interpreter import (
    InterpreterError,
    KernelChoice,
    candidates,
    env_python,
    find_project_python,
    resolve,
    running_kernels,
)


def fake_env(env_dir: Path, *, ipykernel: bool = True) -> Path:
    """A virtualenv whose python only answers the ipykernel import check."""
    python = env_python(env_dir)
    python.parent.mkdir(parents=True)
    python.write_text(f"#!/bin/sh\nexit {0 if ipykernel else 1}\n")
    python.chmod(python.stat().st_mode | stat.S_IEXEC)
    return python


def test_finds_the_nearest_venv_above_the_file(tmp_path):
    python = fake_env(tmp_path / ".venv")
    nested = tmp_path / "src" / "analysis"
    nested.mkdir(parents=True)
    assert find_project_python(nested, env={}) == (python, ".venv")


def test_virtual_env_wins_over_venv(tmp_path):
    fake_env(tmp_path / ".venv")
    active = fake_env(tmp_path / "elsewhere")
    found = find_project_python(tmp_path, env={"VIRTUAL_ENV": str(tmp_path / "elsewhere")})
    assert found == (active, "elsewhere")


def test_no_project_env_uses_pystudios_own_python(tmp_path):
    assert resolve(start=tmp_path, env={}) == KernelChoice()


def test_project_env_with_ipykernel_runs_the_kernel(tmp_path):
    python = fake_env(tmp_path / ".venv")
    assert resolve(start=tmp_path, env={}) == KernelChoice(python=python, label=".venv")


def test_project_env_without_ipykernel_falls_back_with_a_note(tmp_path):
    fake_env(tmp_path / ".venv", ipykernel=False)
    choice = resolve(start=tmp_path, env={})
    assert choice.python is None
    assert choice.kernel_name == "python3"
    assert "uv add --dev ipykernel" in (choice.note or "")


def test_explicit_kernel_skips_detection(tmp_path):
    fake_env(tmp_path / ".venv")
    choice = resolve(kernel_name="other", start=tmp_path, env={})
    assert choice == KernelChoice(kernel_name="other", label="other")


def test_explicit_python_wins(tmp_path):
    fake_env(tmp_path / ".venv")
    python = fake_env(tmp_path / "chosen")
    choice = resolve(python=python, start=tmp_path, env={})
    assert choice == KernelChoice(python=python, label="chosen")


def test_explicit_python_without_ipykernel_is_an_error(tmp_path):
    python = fake_env(tmp_path / "bare", ipykernel=False)
    with pytest.raises(InterpreterError, match="cannot import ipykernel"):
        resolve(python=python, start=tmp_path, env={})


def connection_file(runtime_dir: Path, name: str, port: int) -> Path:
    path = runtime_dir / f"kernel-{name}.json"
    path.write_text(json.dumps({"ip": "127.0.0.1", "transport": "tcp", "shell_port": port}))
    return path


def test_running_kernels_skips_the_ones_that_are_gone(tmp_path):
    with socket.socket() as listener, socket.socket() as closed:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        closed.bind(("127.0.0.1", 0))  # bound but not listening: connections are refused
        alive = connection_file(tmp_path, "alive", listener.getsockname()[1])
        connection_file(tmp_path, "stale", closed.getsockname()[1])
        (tmp_path / "kernel-garbage.json").write_text("not json")
        assert running_kernels(tmp_path) == [alive]
        assert running_kernels(tmp_path, exclude=alive) == []


def test_candidates_lists_project_registered_and_running(tmp_path):
    python = fake_env(tmp_path / ".venv")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        running = connection_file(runtime, "abcdef0123456789", listener.getsockname()[1])
        choices = candidates(
            start=tmp_path, env={}, kernel_names=["python3", "ir"], runtime_dir=runtime
        )
    assert choices == [
        KernelChoice(python=python, label=".venv"),
        KernelChoice(kernel_name="python3", label="python3"),
        KernelChoice(kernel_name="ir", label="ir"),
        KernelChoice(connection_file=running, label="abcdef01"),
    ]
