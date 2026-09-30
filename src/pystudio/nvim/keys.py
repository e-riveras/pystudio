"""Textual input events translated into Neovim's key notation.

Textual names keys as ``"ctrl+a"``, ``"escape"`` or ``"question_mark"``; Neovim
wants ``<C-a>``, ``<Esc>`` and ``?``. Printable characters fall back to
``event.character``, which is what carries punctuation whose Textual name is a
Unicode description.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual import events

SPECIAL: dict[str, str] = {
    "escape": "Esc",
    "enter": "CR",
    "tab": "Tab",
    "backspace": "BS",
    "delete": "Del",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "space": "Space",
    **{f"f{number}": f"F{number}" for number in range(1, 13)},
}

MODIFIERS: tuple[tuple[str, str], ...] = (
    ("ctrl+", "C"),
    ("shift+", "S"),
    ("alt+", "M"),
    ("meta+", "M"),
    ("super+", "D"),
)


def to_nvim(key: str, character: str | None = None) -> str | None:
    """Return Neovim notation for a key name, or None if it cannot be sent."""
    modifiers: list[str] = []
    rest = key
    consumed = True
    while consumed:
        consumed = False
        for prefix, flag in MODIFIERS:
            if rest.startswith(prefix):
                if flag not in modifiers:
                    modifiers.append(flag)
                rest = rest[len(prefix) :]
                consumed = True

    base = SPECIAL.get(rest)
    if base is None:
        if len(rest) == 1:
            base = rest
        elif character and len(character) == 1 and character.isprintable():
            base = character
        else:
            return None

    # A bare `<` would start a key code, so it always goes through its name.
    if base == "<":
        base = "lt"
    elif not modifiers and len(base) == 1:
        return base

    return f"<{'-'.join([*modifiers, base])}>"


def key_event_to_nvim(event: events.Key) -> str | None:
    """Translate a Textual key event."""
    return to_nvim(event.key, event.character)


def mouse_modifiers(event: events.MouseEvent) -> str:
    """Modifier string for ``nvim_input_mouse``: single chars, concatenated."""
    modifiers = ""
    if event.ctrl:
        modifiers += "C"
    if event.shift:
        modifiers += "S"
    if event.meta:
        modifiers += "M"
    return modifiers


BUTTONS: dict[int, str] = {1: "left", 2: "middle", 3: "right"}


def mouse_button(event: events.MouseEvent) -> str | None:
    """``left``, ``middle`` or ``right`` for a Textual mouse event."""
    return BUTTONS.get(getattr(event, "button", 0))
