"""Synthetic keyboard events via CGEvent.

ANSI US-layout virtual key codes, keyed by lower-cased name/alias. These
hardware codes are stable regardless of the active input source; the active
layout only affects which character the code produces, which is irrelevant for
shortcuts (cmd+c is the physical "c" key with the command flag).
"""

import time
from typing import Optional, Tuple

from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskSecondaryFn,
    kCGEventFlagMaskShift,
    kCGHIDEventTap,
)

from .errors import CLIError
from .key_names import KEY_CODES, key_hold_components


def _sleep_us(microseconds: int) -> None:
    time.sleep(microseconds / 1_000_000.0)


_KEY_CODES = KEY_CODES


def _modifier_flag(name: str) -> Optional[int]:
    if name in ("cmd", "command", "meta", "super", "win", "⌘"):
        return kCGEventFlagMaskCommand
    if name in ("shift", "⇧"):
        return kCGEventFlagMaskShift
    if name in ("ctrl", "control", "ctl", "⌃"):
        return kCGEventFlagMaskControl
    if name in ("opt", "option", "alt", "⌥"):
        return kCGEventFlagMaskAlternate
    if name in ("fn", "function"):
        return kCGEventFlagMaskSecondaryFn
    return None


_SHIFTED_ASCII = {
    33: 0x12,   # !
    34: 0x27,   # "
    35: 0x14,   # #
    36: 0x15,   # $
    37: 0x17,   # %
    38: 0x1A,   # &
    40: 0x19,   # (
    41: 0x1D,   # )
    42: 0x1C,   # *
    43: 0x18,   # +
    58: 0x29,   # :
    60: 0x2B,   # <
    62: 0x2F,   # >
    63: 0x2C,   # ?
    64: 0x13,   # @
    94: 0x16,   # ^
    95: 0x1B,   # _
    123: 0x21,  # {
    124: 0x2A,  # |
    125: 0x1E,  # }
    126: 0x32,  # ~
}

_UNSHIFTED_ASCII = {
    32: 0x31,  # space
    39: 0x27,  # '
    44: 0x2B,  # ,
    45: 0x1B,  # -
    46: 0x2F,  # .
    47: 0x2C,  # /
    48: 0x1D,  # 0
    49: 0x12,  # 1
    50: 0x13,  # 2
    51: 0x14,  # 3
    52: 0x15,  # 4
    53: 0x17,  # 5
    54: 0x16,  # 6
    55: 0x1A,  # 7
    56: 0x1C,  # 8
    57: 0x19,  # 9
    59: 0x29,  # ;
    61: 0x18,  # =
    91: 0x21,  # [
    92: 0x2A,  # \
    93: 0x1E,  # ]
    96: 0x32,  # `
}


def _physical_keystroke(character: str) -> Optional[Tuple[int, int]]:
    if len(character) != 1:
        return None
    value = ord(character)
    if value >= 128:
        return None

    if 65 <= value <= 90:  # A-Z
        code = _KEY_CODES.get(chr(value + 32))
        if code is None:
            return None
        return (code, kCGEventFlagMaskShift)
    if 97 <= value <= 122:  # a-z
        code = _KEY_CODES.get(character)
        if code is None:
            return None
        return (code, 0)
    if value in _UNSHIFTED_ASCII:
        return (_UNSHIFTED_ASCII[value], 0)
    if value in _SHIFTED_ASCII:
        return (_SHIFTED_ASCII[value], kCGEventFlagMaskShift)
    return None


def parse_key_combo(raw: str) -> Tuple[int, int]:
    """Parse a combo like `cmd+shift+a` into a base key code plus modifier flags.

    A stray or trailing `+` is rejected rather than silently producing the wrong
    keystroke — to press the literal plus key use `shift+=` or the name `plus`.
    """
    trimmed = raw.strip()
    if not trimmed:
        raise CLIError("--key is empty", code=2)

    parts = [p.strip().lower() for p in trimmed.split("+")]

    flags = 0
    base_key: Optional[str] = None

    for part in parts:
        if not part:
            raise CLIError(
                f"malformed key combo '{raw}': stray or trailing '+'. "
                "To press the plus key use 'shift+=' or 'plus'.",
                code=2,
            )
        flag = _modifier_flag(part)
        if flag is not None:
            flags |= flag
            continue
        if base_key is not None:
            raise CLIError(f"multiple non-modifier keys in '{raw}' (only one allowed)", code=2)
        base_key = part

    if base_key is None:
        raise CLIError(f"no key specified in '{raw}' (modifiers only)", code=2)

    # "plus" is the shifted '=' key.
    if base_key == "plus":
        flags |= kCGEventFlagMaskShift
        return (0x18, flags)
    code = _KEY_CODES.get(base_key)
    if code is None:
        raise CLIError(f"unknown key '{base_key}' in '{raw}'", code=2)
    return (code, flags)


def perform_key_event(code: int, flags: int, down: bool, source) -> None:
    """Post a single key-down or key-up (for held-key sequences like shift+click)."""
    event = CGEventCreateKeyboardEvent(source, code, down)
    if event is not None:
        CGEventSetFlags(event, flags)
        CGEventPost(kCGHIDEventTap, event)
    _sleep_us(8_000)


def perform_key_down(raw: str, source) -> None:
    for code in key_hold_components(raw):
        event = CGEventCreateKeyboardEvent(source, code, True)
        if event is not None:
            CGEventPost(kCGHIDEventTap, event)
        _sleep_us(8_000)


def perform_key_up(raw: str, source) -> None:
    for code in reversed(key_hold_components(raw)):
        event = CGEventCreateKeyboardEvent(source, code, False)
        if event is not None:
            CGEventPost(kCGHIDEventTap, event)
        _sleep_us(8_000)


def perform_key_combo(code: int, flags: int, source) -> None:
    """Press and release a key code with the given modifier flags held."""
    down = CGEventCreateKeyboardEvent(source, code, True)
    if down is not None:
        CGEventSetFlags(down, flags)
        CGEventPost(kCGHIDEventTap, down)
    _sleep_us(12_000)

    up = CGEventCreateKeyboardEvent(source, code, False)
    if up is not None:
        CGEventSetFlags(up, flags)
        CGEventPost(kCGHIDEventTap, up)
    _sleep_us(8_000)


def perform_type_text(text: str, source) -> None:
    """Type literal text. Printable ASCII is sent as physical key presses because
    system UI such as Spotlight may ignore Unicode-only keyboard events. Other
    characters fall back to Unicode events.
    """
    for character in text:
        if character == "\n":
            perform_key_combo(0x24, 0, source)  # Return
            continue
        if character == "\t":
            perform_key_combo(0x30, 0, source)  # Tab
            continue

        key = _physical_keystroke(character)
        if key is not None:
            perform_key_combo(key[0], key[1], source)
            continue

        utf16_len = len(character.encode("utf-16-le")) // 2

        down = CGEventCreateKeyboardEvent(source, 0, True)
        if down is not None:
            CGEventKeyboardSetUnicodeString(down, utf16_len, character)
            CGEventPost(kCGHIDEventTap, down)

        up = CGEventCreateKeyboardEvent(source, 0, False)
        if up is not None:
            CGEventKeyboardSetUnicodeString(up, utf16_len, character)
            CGEventPost(kCGHIDEventTap, up)

        _sleep_us(3_000)
