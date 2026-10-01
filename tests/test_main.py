from __future__ import annotations

import stat

import pytest

from pystudio.__main__ import main, nvim_version


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
