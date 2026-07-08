"""Synthetic mouse events via CGEvent."""

import enum
import math
import time
from typing import Optional, Tuple

from CoreFoundation import CFPreferencesCopyAppValue, kCFPreferencesAnyApplication
from Quartz import (
    CGEventCreate,
    CGEventCreateMouseEvent,
    CGEventCreateScrollWheelEvent,
    CGEventGetLocation,
    CGEventPost,
    CGEventSetIntegerValueField,
    CGEventSourceCreate,
    CGPointMake,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseDragged,
    kCGEventLeftMouseUp,
    kCGEventMouseMoved,
    kCGEventOtherMouseDown,
    kCGEventOtherMouseDragged,
    kCGEventOtherMouseUp,
    kCGEventRightMouseDown,
    kCGEventRightMouseDragged,
    kCGEventRightMouseUp,
    kCGEventSourceStateCombinedSessionState,
    kCGHIDEventTap,
    kCGMouseButtonCenter,
    kCGMouseButtonLeft,
    kCGMouseButtonRight,
    kCGMouseEventClickState,
    kCGScrollEventUnitLine,
)

from .errors import CLIError


def _sleep_us(microseconds: int) -> None:
    time.sleep(microseconds / 1_000_000.0)


class MouseButton(enum.Enum):
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"

    @staticmethod
    def parse(raw: str) -> "MouseButton":
        low = raw.lower()
        if low in ("left", "l", "primary"):
            return MouseButton.LEFT
        if low in ("right", "r", "secondary"):
            return MouseButton.RIGHT
        if low in ("center", "middle", "c", "m"):
            return MouseButton.CENTER
        raise CLIError(f"--mouse-button must be left|right|center (got '{raw}')", code=2)

    @property
    def cg_button(self) -> int:
        return {
            MouseButton.LEFT: kCGMouseButtonLeft,
            MouseButton.RIGHT: kCGMouseButtonRight,
            MouseButton.CENTER: kCGMouseButtonCenter,
        }[self]

    @property
    def click_types(self) -> Tuple[int, int]:
        """Down / up event types for this button."""
        return {
            MouseButton.LEFT: (kCGEventLeftMouseDown, kCGEventLeftMouseUp),
            MouseButton.RIGHT: (kCGEventRightMouseDown, kCGEventRightMouseUp),
            MouseButton.CENTER: (kCGEventOtherMouseDown, kCGEventOtherMouseUp),
        }[self]

    @property
    def drag_type(self) -> int:
        return {
            MouseButton.LEFT: kCGEventLeftMouseDragged,
            MouseButton.RIGHT: kCGEventRightMouseDragged,
            MouseButton.CENTER: kCGEventOtherMouseDragged,
        }[self]


class ScrollDirection(enum.Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

    @staticmethod
    def parse(raw: str) -> "ScrollDirection":
        try:
            return ScrollDirection(raw.lower())
        except ValueError:
            raise CLIError(f"--direction must be up|down|left|right (got '{raw}')", code=2)


def event_source():
    """Shared event source for all generated events."""
    return CGEventSourceCreate(kCGEventSourceStateCombinedSessionState)


def _post(event) -> None:
    if event is not None:
        CGEventPost(kCGHIDEventTap, event)


def move_mouse(point, source) -> None:
    """Warp the cursor to a point in one event (instant; used per-step internally)."""
    _post(
        CGEventCreateMouseEvent(
            source, kCGEventMouseMoved, CGPointMake(point.x, point.y), kCGMouseButtonLeft
        )
    )


def current_mouse_location():
    """Current cursor location in global (top-left origin) coordinates."""
    event = CGEventCreate(None)
    if event is None:
        return CGPointMake(0, 0)
    return CGEventGetLocation(event)


def smooth_move(target, source) -> None:
    """Glide the cursor to `target` along an eased path instead of teleporting."""
    start = current_mouse_location()
    dx = target.x - start.x
    dy = target.y - start.y
    distance = math.sqrt(dx * dx + dy * dy)
    if distance < 1:
        move_mouse(target, source)
        return
    steps = max(12, min(60, int(distance / 12)))
    for i in range(1, steps + 1):
        t = i / steps
        # ease-in-out
        e = 2 * t * t if t < 0.5 else 1 - math.pow(-2 * t + 2, 2) / 2
        move_mouse(CGPointMake(start.x + dx * e, start.y + dy * e), source)
        _sleep_us(6_000)


def perform_click(point, button: MouseButton, click_count: int, source) -> None:
    """Click at a point. `click_count` >= 2 produces a proper multi-click by
    incrementing the click-state field on each successive down/up pair.
    """
    count = max(1, click_count)
    down_type, up_type = button.click_types

    smooth_move(point, source)
    _sleep_us(12_000)

    for n in range(1, count + 1):
        down = CGEventCreateMouseEvent(
            source, down_type, CGPointMake(point.x, point.y), button.cg_button
        )
        if down is not None:
            CGEventSetIntegerValueField(down, kCGMouseEventClickState, n)
        _post(down)
        _sleep_us(12_000)

        up = CGEventCreateMouseEvent(
            source, up_type, CGPointMake(point.x, point.y), button.cg_button
        )
        if up is not None:
            CGEventSetIntegerValueField(up, kCGMouseEventClickState, n)
        _post(up)
        _sleep_us(12_000)


def perform_mouse_down(point, button: MouseButton, source) -> None:
    smooth_move(point, source)
    _sleep_us(12_000)
    down = CGEventCreateMouseEvent(
        source, button.click_types[0], CGPointMake(point.x, point.y), button.cg_button
    )
    if down is not None:
        CGEventSetIntegerValueField(down, kCGMouseEventClickState, 1)
    _post(down)


def perform_mouse_up(point, button: MouseButton, source) -> None:
    up = CGEventCreateMouseEvent(
        source, button.click_types[1], CGPointMake(point.x, point.y), button.cg_button
    )
    if up is not None:
        CGEventSetIntegerValueField(up, kCGMouseEventClickState, 1)
    _post(up)


def perform_drag(from_point, to_point, button: MouseButton, source) -> None:
    """Press at `from`, drag through interpolated points, release at `to`."""
    down_type, up_type = button.click_types

    smooth_move(from_point, source)
    _sleep_us(20_000)

    down = CGEventCreateMouseEvent(
        source, down_type, CGPointMake(from_point.x, from_point.y), button.cg_button
    )
    if down is not None:
        CGEventSetIntegerValueField(down, kCGMouseEventClickState, 1)
    _post(down)
    _sleep_us(40_000)

    steps = 40
    for i in range(1, steps + 1):
        t = i / steps
        px = from_point.x + (to_point.x - from_point.x) * t
        py = from_point.y + (to_point.y - from_point.y) * t
        drag = CGEventCreateMouseEvent(source, button.drag_type, CGPointMake(px, py), button.cg_button)
        if drag is not None:
            CGEventSetIntegerValueField(drag, kCGMouseEventClickState, 1)
        _post(drag)
        _sleep_us(8_000)

    _sleep_us(30_000)
    up = CGEventCreateMouseEvent(
        source, up_type, CGPointMake(to_point.x, to_point.y), button.cg_button
    )
    if up is not None:
        CGEventSetIntegerValueField(up, kCGMouseEventClickState, 1)
    _post(up)


def natural_scrolling_enabled() -> bool:
    """Whether macOS "natural scrolling" is enabled (the default for trackpads)."""
    value = CFPreferencesCopyAppValue(
        "com.apple.swipescrolldirection", kCFPreferencesAnyApplication
    )
    if value is None:
        return False
    return bool(value)


def perform_scroll(
    direction: ScrollDirection,
    pages: int,
    lines_per_page: int,
    point,
    source,
) -> None:
    """Scroll `pages` pages in a direction, optionally after moving the cursor.

    `direction` is interpreted from the user's point of view regardless of the
    "natural scrolling" preference (we read it and flip the wheel signs).
    """
    if point is not None:
        smooth_move(point, source)
        _sleep_us(12_000)

    # Raw CoreGraphics convention (natural scrolling OFF): positive wheel1 reveals
    # content above ("up"), positive wheel2 reveals content to the left.
    flip = -1 if natural_scrolling_enabled() else 1
    total_lines = max(1, pages) * max(1, lines_per_page)
    for _ in range(total_lines):
        wheel1 = 0  # vertical
        wheel2 = 0  # horizontal
        if direction == ScrollDirection.UP:
            wheel1 = 1
        elif direction == ScrollDirection.DOWN:
            wheel1 = -1
        elif direction == ScrollDirection.LEFT:
            wheel2 = 1
        elif direction == ScrollDirection.RIGHT:
            wheel2 = -1
        # pyobjc's variadic wrapper takes exactly `wheelCount` wheel values.
        event = CGEventCreateScrollWheelEvent(
            source, kCGScrollEventUnitLine, 2, wheel1 * flip, wheel2 * flip
        )
        _post(event)
        _sleep_us(6_000)
