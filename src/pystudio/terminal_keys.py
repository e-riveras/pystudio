"""Textual key events as the bytes an xterm would send to the program in it."""

from __future__ import annotations

CSI = "\x1b["

CURSOR = {"up": "A", "down": "B", "right": "C", "left": "D", "home": "H", "end": "F"}
"""Keys sent as ``CSI x``, or ``SS3 x`` in application cursor mode, or
``CSI 1;m x`` with modifiers."""

TILDE = {
    "insert": 2,
    "delete": 3,
    "pageup": 5,
    "pagedown": 6,
    "f5": 15,
    "f6": 17,
    "f7": 18,
    "f8": 19,
    "f9": 20,
    "f10": 21,
    "f11": 23,
    "f12": 24,
}
"""Keys sent as ``CSI n ~``, or ``CSI n;m ~`` with modifiers."""

PLAIN = {
    "enter": "\r",
    "tab": "\t",
    "backspace": "\x7f",
    "escape": "\x1b",
    "shift+tab": CSI + "Z",
    # No terminal sends shift+enter on its own; agent CLIs such as Claude Code
    # read meta+enter as "new line without submitting".
    "shift+enter": "\x1b\r",
    "ctrl+space": "\x00",
    "ctrl+@": "\x00",
    "f1": "\x1bOP",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
    "f4": "\x1bOS",
}

MODIFIER_BITS = {"shift": 1, "alt": 2, "ctrl": 4}


def key_to_bytes(key: str, character: str | None, *, app_cursor: bool = False) -> bytes | None:
    """The bytes for one key, or None for a key with no terminal meaning."""
    if key in PLAIN:
        return PLAIN[key].encode()

    *modifiers, name = key.split("+") if key != "+" else ["+"]
    bits = sum(MODIFIER_BITS.get(modifier, 0) for modifier in modifiers)

    if name in CURSOR:
        if bits:
            return f"{CSI}1;{bits + 1}{CURSOR[name]}".encode()
        return (("\x1bO" if app_cursor else CSI) + CURSOR[name]).encode()
    if name in TILDE:
        suffix = f";{bits + 1}" if bits else ""
        return f"{CSI}{TILDE[name]}{suffix}~".encode()

    if modifiers == ["ctrl"] and len(name) == 1 and name.isalpha():
        return bytes([ord(name.lower()) - ord("a") + 1])
    if modifiers and modifiers[0] == "alt":
        rest = key_to_bytes("+".join([*modifiers[1:], name]), character, app_cursor=app_cursor)
        if rest is None and len(name) == 1:
            rest = name.encode()
        return b"\x1b" + rest if rest is not None else None

    if character and character.isprintable():
        return character.encode()
    return None
