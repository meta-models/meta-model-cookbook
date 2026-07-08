"""The manipulation backend the agent drives."""

import time
from typing import Optional

from .keyboard import (
    parse_key_combo,
    perform_key_combo,
    perform_key_down,
    perform_key_up,
    perform_type_text,
)
from .mouse import (
    MouseButton,
    ScrollDirection,
    event_source,
    perform_click,
    perform_drag,
    perform_mouse_down,
    perform_mouse_up,
    perform_scroll,
    smooth_move,
)
from .screenshot import Screenshot, capture_screenshot


class ManipulationBackend:
    label = ""
    requires_accessibility = False
    requires_screen_recording = False
    supports_background = False
    supports_multiple_cursors = False

    def screenshot(self, scale: float = 1.0) -> Screenshot:
        raise NotImplementedError

    def move(self, point) -> None:
        raise NotImplementedError

    def click(self, point, button: MouseButton, click_count: int) -> None:
        raise NotImplementedError

    def mouse_down(self, point, button: MouseButton) -> None:
        raise NotImplementedError

    def mouse_up(self, point, button: MouseButton) -> None:
        raise NotImplementedError

    def scroll(self, direction: ScrollDirection, pages: int, lines_per_page: int, point) -> None:
        raise NotImplementedError

    def drag(self, from_point, to_point, button: MouseButton) -> None:
        raise NotImplementedError

    def press_key(self, key: str) -> None:
        raise NotImplementedError

    def key_down(self, key: str) -> None:
        raise NotImplementedError

    def key_up(self, key: str) -> None:
        raise NotImplementedError

    def type_text(self, text: str) -> None:
        raise NotImplementedError

    def wait(self, ms: int) -> None:
        raise NotImplementedError


def make_manipulation_backend(config) -> ManipulationBackend:
    return CGEventManipulationBackend()


class CGEventManipulationBackend(ManipulationBackend):
    label = "CGEvent foreground"
    requires_accessibility = True
    requires_screen_recording = True
    supports_background = False
    supports_multiple_cursors = False

    def __init__(self):
        self._source = event_source()

    def screenshot(self, scale: float = 1.0) -> Screenshot:
        return capture_screenshot(scale)

    def move(self, point) -> None:
        smooth_move(point, self._source)

    def click(self, point, button: MouseButton, click_count: int) -> None:
        perform_click(point, button, click_count, self._source)

    def mouse_down(self, point, button: MouseButton) -> None:
        perform_mouse_down(point, button, self._source)

    def mouse_up(self, point, button: MouseButton) -> None:
        perform_mouse_up(point, button, self._source)

    def scroll(self, direction: ScrollDirection, pages: int, lines_per_page: int, point) -> None:
        perform_scroll(direction, pages, lines_per_page, point, self._source)

    def drag(self, from_point, to_point, button: MouseButton) -> None:
        perform_drag(from_point, to_point, button, self._source)

    def press_key(self, key: str) -> None:
        code, flags = parse_key_combo(key)
        perform_key_combo(code, flags, self._source)

    def key_down(self, key: str) -> None:
        perform_key_down(key, self._source)

    def key_up(self, key: str) -> None:
        perform_key_up(key, self._source)

    def type_text(self, text: str) -> None:
        perform_type_text(text, self._source)

    def wait(self, ms: int) -> None:
        time.sleep(ms / 1000.0)
