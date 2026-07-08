"""Pure virtual-key name tables shared by keyboard event code and tests."""

from typing import Optional

from .errors import CLIError


def build_key_codes() -> dict:
    m: dict = {}

    m.update({
        "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04,
        "g": 0x05, "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09,
        "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F,
        "y": 0x10, "t": 0x11, "o": 0x1F, "u": 0x20, "i": 0x22,
        "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D,
        "m": 0x2E,
    })
    m.update({
        "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
        "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,
    })
    m.update({
        "=": 0x18, "equal": 0x18, "equals": 0x18,
        "-": 0x1B, "minus": 0x1B,
        "]": 0x1E, "rightbracket": 0x1E,
        "[": 0x21, "leftbracket": 0x21,
        "'": 0x27, "quote": 0x27, "apostrophe": 0x27,
        ";": 0x29, "semicolon": 0x29,
        "\\": 0x2A, "backslash": 0x2A,
        ",": 0x2B, "comma": 0x2B,
        "/": 0x2C, "slash": 0x2C,
        ".": 0x2F, "period": 0x2F, "dot": 0x2F,
        "`": 0x32, "grave": 0x32, "backtick": 0x32, "tilde": 0x32,
    })
    m.update({
        "return": 0x24, "enter": 0x24, "\n": 0x24,
        "tab": 0x30, "\t": 0x30,
        "space": 0x31, "spacebar": 0x31, " ": 0x31,
        "delete": 0x33, "backspace": 0x33, "bksp": 0x33,
        "escape": 0x35, "esc": 0x35,
        "forwarddelete": 0x75, "forward-delete": 0x75, "fwddelete": 0x75, "del": 0x75,
        "keypadenter": 0x4C, "kpenter": 0x4C,
        "capslock": 0x39,
        "help": 0x72, "insert": 0x72,
        "home": 0x73, "end": 0x77,
        "pageup": 0x74, "pgup": 0x74,
        "pagedown": 0x79, "pgdn": 0x79, "pagedn": 0x79,
        "left": 0x7B, "leftarrow": 0x7B,
        "right": 0x7C, "rightarrow": 0x7C,
        "down": 0x7D, "downarrow": 0x7D,
        "up": 0x7E, "uparrow": 0x7E,
    })
    m.update({
        "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
        "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
        "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
        "f13": 0x69, "f14": 0x6B, "f15": 0x71, "f16": 0x6A,
        "f17": 0x40, "f18": 0x4F, "f19": 0x50, "f20": 0x5A,
    })
    return m


KEY_CODES = build_key_codes()

MODIFIER_KEY_CODES = {
    "cmd": 0x37, "command": 0x37, "meta": 0x37, "super": 0x37, "win": 0x37, "⌘": 0x37,
    "shift": 0x38, "⇧": 0x38,
    "ctrl": 0x3B, "control": 0x3B, "ctl": 0x3B, "⌃": 0x3B,
    "opt": 0x3A, "option": 0x3A, "alt": 0x3A, "⌥": 0x3A,
    "fn": 0x3F, "function": 0x3F,
}


def key_hold_components(raw: str):
    parts = [p.strip().lower() for p in str(raw).split("+")]
    if not parts or any(not p for p in parts):
        raise CLIError(f"malformed key hold '{raw}'", code=2)
    codes = []
    for part in parts:
        code: Optional[int] = MODIFIER_KEY_CODES.get(part)
        if code is None:
            code = KEY_CODES.get(part)
        if code is None:
            raise CLIError(f"unknown key '{part}' in '{raw}'", code=2)
        codes.append(code)
    return codes
