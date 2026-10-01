from __future__ import annotations

import stat
from pathlib import Path

import pytest

from pystudio.interpreter import (
    InterpreterError,
    KernelChoice,
    env_python,
    find_project_python,
    resolve,
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
