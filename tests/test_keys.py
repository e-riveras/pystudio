"""Key translation, which has no dependencies worth mocking."""

from __future__ import annotations

import pytest

from pystudio.nvim.keys import to_nvim


@pytest.mark.parametrize(
    ("key", "character", "expected"),
    [
        ("a", "a", "a"),
        ("A", "A", "A"),
        ("ctrl+a", "\x01", "<C-a>"),
        ("escape", None, "<Esc>"),
        ("enter", "\r", "<CR>"),
        ("tab", "\t", "<Tab>"),
        ("shift+tab", None, "<S-Tab>"),
        ("backspace", None, "<BS>"),
        ("space", " ", "<Space>"),
        ("up", None, "<Up>"),
        ("f5", None, "<F5>"),
        ("alt+x", "x", "<M-x>"),
        ("ctrl+shift+left", None, "<C-S-Left>"),
        ("question_mark", "?", "?"),
        ("less_than_sign", "<", "<lt>"),
        ("ctrl+less_than_sign", "<", "<C-lt>"),
    ],
)
def test_translation(key: str, character: str | None, expected: str) -> None:
    assert to_nvim(key, character) == expected


def test_unsendable_keys_are_dropped() -> None:
    assert to_nvim("scroll_lock", None) is None
    assert to_nvim("ctrl+scroll_lock", None) is None
