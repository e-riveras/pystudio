from __future__ import annotations

import pytest

from pystudio.terminal_keys import key_to_bytes


@pytest.mark.parametrize(
    ("key", "character", "expected"),
    [
        ("a", "a", b"a"),
        ("é", "é", "é".encode()),
        ("enter", "\r", b"\r"),
        ("backspace", None, b"\x7f"),
        ("escape", None, b"\x1b"),
        ("shift+tab", None, b"\x1b[Z"),
        ("shift+enter", None, b"\x1b\r"),
        ("ctrl+c", None, b"\x03"),
        ("ctrl+a", None, b"\x01"),
        ("up", None, b"\x1b[A"),
        ("ctrl+left", None, b"\x1b[1;5D"),
        ("shift+up", None, b"\x1b[1;2A"),
        ("delete", None, b"\x1b[3~"),
        ("pagedown", None, b"\x1b[6~"),
        ("f1", None, b"\x1bOP"),
        ("f12", None, b"\x1b[24~"),
        ("alt+b", None, b"\x1bb"),
        ("alt+backspace", None, b"\x1b\x7f"),
    ],
)
def test_key_bytes(key, character, expected) -> None:
    assert key_to_bytes(key, character) == expected


def test_application_cursor_mode_uses_ss3() -> None:
    assert key_to_bytes("up", None, app_cursor=True) == b"\x1bOA"


def test_keys_without_a_terminal_meaning_are_dropped() -> None:
    assert key_to_bytes("ctrl+f13", None) is None
