"""Keyboard-controlled pointer mode in a raw terminal."""

import enum
import os
import sys
import termios

from Quartz import CGDisplayBounds, CGMainDisplayID, CGPointMake

from .app_control import activate_app
from .args import Args
from .errors import CLIError
from .mouse import (
    MouseButton,
    current_mouse_location,
    event_source,
    move_mouse,
    perform_click,
)
from .permissions import require_trust


class _PointerKey(enum.Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    CLICK = "click"
    FASTER = "faster"
    SLOWER = "slower"
    QUIT = "quit"


def run_pointer_control(raw) -> None:
    if not sys.stdin.isatty():
        raise CLIError("pointer mode requires an interactive terminal", code=2)

    args = Args(raw)
    step = args.int("step") or 20
    if step < 1:
        raise CLIError("--step must be >= 1", code=2)

    require_trust()
    if args.string("app"):
        activate_app(args.string("app"))

    source = event_source()
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)

    raw_mode = termios.tcgetattr(fd)
    # lflags index is 3; disable ECHO, ICANON, ISIG.
    raw_mode[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
    raw_mode[6][termios.VMIN] = 0
    raw_mode[6][termios.VTIME] = 1  # tenths of a second
    termios.tcsetattr(fd, termios.TCSANOW, raw_mode)

    print("pointer mode: arrows/WASD move, space/return click, +/- changes step, q quits")
    print(f"step: {step}")
    sys.stdout.flush()

    try:
        while True:
            key = _read_pointer_key(fd)
            if key is None:
                continue
            if key == _PointerKey.UP:
                _nudge_pointer(0, -step, source)
            elif key == _PointerKey.DOWN:
                _nudge_pointer(0, step, source)
            elif key == _PointerKey.LEFT:
                _nudge_pointer(-step, 0, source)
            elif key == _PointerKey.RIGHT:
                _nudge_pointer(step, 0, source)
            elif key == _PointerKey.CLICK:
                perform_click(current_mouse_location(), MouseButton.LEFT, 1, source)
            elif key == _PointerKey.FASTER:
                step = min(step * 2, 400)
                print(f"\rstep: {step}   ", end="")
                sys.stdout.flush()
            elif key == _PointerKey.SLOWER:
                step = max(step // 2, 1)
                print(f"\rstep: {step}   ", end="")
                sys.stdout.flush()
            elif key == _PointerKey.QUIT:
                return
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        sys.stdout.write("\n")
        sys.stdout.flush()


def _read_pointer_key(fd):
    byte = _read_byte(fd)
    if byte is None:
        return None
    if byte in (3, 4, 27):
        if byte == 27:
            nxt = _read_byte(fd)
            if nxt == 91:
                arrow = _read_byte(fd)
                if arrow == 65:
                    return _PointerKey.UP
                if arrow == 66:
                    return _PointerKey.DOWN
                if arrow == 67:
                    return _PointerKey.RIGHT
                if arrow == 68:
                    return _PointerKey.LEFT
                return None
        return _PointerKey.QUIT
    if byte in (10, 13, 32):
        return _PointerKey.CLICK
    if byte in (43, 61):
        return _PointerKey.FASTER
    if byte in (45, 95):
        return _PointerKey.SLOWER
    if byte in (65, 97):
        return _PointerKey.LEFT
    if byte in (68, 100):
        return _PointerKey.RIGHT
    if byte in (81, 113):
        return _PointerKey.QUIT
    if byte in (83, 115):
        return _PointerKey.DOWN
    if byte in (87, 119):
        return _PointerKey.UP
    return None


def _read_byte(fd):
    data = os.read(fd, 1)
    if len(data) == 1:
        return data[0]
    return None


def _nudge_pointer(dx, dy, source):
    current = current_mouse_location()
    move_mouse(_clamp_to_main_display(CGPointMake(current.x + dx, current.y + dy)), source)


def _clamp_to_main_display(point):
    bounds = CGDisplayBounds(CGMainDisplayID())
    width = bounds.size.width
    height = bounds.size.height
    if width <= 0 or height <= 0:
        return point
    min_x = bounds.origin.x
    min_y = bounds.origin.y
    max_x = min_x + width
    max_y = min_y + height
    return CGPointMake(
        min(max(min_x, point.x), max_x - 1),
        min(max(min_y, point.y), max_y - 1),
    )
