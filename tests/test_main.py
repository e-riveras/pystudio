from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from pystudio.__main__ import demo_problem, main, nvim_version


def fake_nvim(tmp_path, version_line: str) -> str:
    script = tmp_path / "nvim"
    script.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_reads_the_version(tmp_path):
    assert nvim_version(fake_nvim(tmp_path, "NVIM v0.12.5")) == (0, 12)


def test_unreadable_version_is_none(tmp_path):
    assert nvim_version(fake_nvim(tmp_path, "something else")) is None


def test_refuses_an_old_neovim(tmp_path, capsys):
    assert main(["--nvim", fake_nvim(tmp_path, "NVIM v0.9.5")]) == 1
    assert "needs Neovim 0.10 or newer, found 0.9" in capsys.readouterr().err


def test_refuses_a_missing_neovim(capsys):
    assert main(["--nvim", "no-such-nvim-here"]) == 1
    assert "cannot find" in capsys.readouterr().err


@pytest.mark.parametrize("line", ["NVIM v0.10.0", "NVIM v1.0.0"])
def test_accepts_a_new_enough_neovim(tmp_path, line):
    assert nvim_version(fake_nvim(tmp_path, line)) >= (0, 10)


@pytest.fixture
def started(tmp_path, monkeypatch):
    """Run ``main`` up to the point of starting the app, and capture how it was built."""
    built: dict = {}

    class App:
        def __init__(self, **kwargs) -> None:
            built.update(kwargs)

        def run(self) -> None:
            pass

    monkeypatch.setattr("pystudio.app.PyStudioApp", App)
    monkeypatch.delenv("PYSTUDIO_ASSISTANT", raising=False)
    monkeypatch.delenv("PYSTUDIO_AGENT", raising=False)
    nvim = fake_nvim(tmp_path, "NVIM v0.12.5")

    def run(*argv: str) -> dict:
        built.clear()
        assert main(["--nvim", nvim, "--kernel", "python3", *argv]) == 0
        return dict(built)

    return run


def test_ai_features_are_off_by_default(started):
    built = started()
    assert built["assistant"] is None
    assert built["agent"] is None


def test_flags_turn_the_ai_features_on(started):
    built = started("--assistant", "--agent")
    assert built["assistant"] == "anthropic"
    assert built["agent"] == "claude"


def test_the_environment_turns_them_on_too(started, monkeypatch):
    monkeypatch.setenv("PYSTUDIO_AGENT", "claude")
    built = started()
    assert built["agent"] == "claude"
    assert built["assistant"] is None


def test_a_file_after_a_flag_is_the_file(started, tmp_path):
    script = tmp_path / "analysis.py"
    built = started("--agent", str(script))
    assert built["agent"] == "claude"
    assert built["path"] == script


def test_an_unknown_agent_is_refused(tmp_path, capsys):
    nvim = fake_nvim(tmp_path, "NVIM v0.12.5")
    assert main(["--nvim", nvim, "a.py", "--agent", "hal"]) == 1
    assert "unknown agent 'hal'; known: claude" in capsys.readouterr().err


def test_a_missing_extra_says_how_to_install_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("pystudio.__main__.EXTRAS", {"agent": ("no_such_module_here",)})
    nvim = fake_nvim(tmp_path, "NVIM v0.12.5")
    assert main(["--nvim", nvim, "--agent"]) == 1
    assert "pystudio-tui[agent]" in capsys.readouterr().err


def test_demo_opens_a_copy_of_the_tour(started, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    built = started("--demo")
    assert built["path"] == tmp_path / "pystudio_demo.py"
    assert "pystudio guided tour" in built["path"].read_text()


def test_demo_keeps_a_copy_that_was_edited(started, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pystudio_demo.py").write_text("mine = 1\n")
    assert started("--demo")["path"].read_text() == "mine = 1\n"


def test_demo_says_what_the_interpreter_lacks(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bare = tmp_path / "python"
    bare.write_text("#!/bin/sh\nexit 1\n")
    bare.chmod(bare.stat().st_mode | stat.S_IEXEC)
    assert demo_problem(bare) is not None and "pystudio-tui[demo]" in demo_problem(bare)
    assert demo_problem(Path(sys.executable)) is None
