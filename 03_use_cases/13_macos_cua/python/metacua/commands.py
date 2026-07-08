"""Manual tool subcommands: click, moveto, scroll, drag, press-key, type-text, shot."""

import base64
import os

from Quartz import CGPointMake

from .app_control import activate_app
from .args import Args
from .errors import CLIError
from .mouse import (
    MouseButton,
    ScrollDirection,
    event_source,
    move_mouse,
    perform_click,
    perform_drag,
    perform_scroll,
)
from .keyboard import parse_key_combo, perform_key_combo, perform_type_text
from .permissions import require_screen_recording, require_trust
from .screenshot import capture_screenshot


def _preflight(app: str) -> None:
    """Common setup for every action: verify permission, then bring the app forward."""
    require_trust()
    activate_app(app)


def run_click(raw) -> None:
    args = Args(raw)
    x = args.required_double("x")
    y = args.required_double("y")
    click_count = args.int("click-count") or args.int("clicks") or 1
    button = MouseButton.parse(args.string(["mouse-button", "button"]) or "left")
    app = args.required_string("app")
    point = CGPointMake(x, y)

    _preflight(app)
    perform_click(point, button, click_count, event_source())
    print(f"clicked {button.value} x{max(1, click_count)} at ({x}, {y}) in {app}")


def run_shot(raw) -> None:
    args = Args(raw)
    require_screen_recording()
    scale = args.double("scale")
    scale = 1.0 if scale is None else scale
    shot = capture_screenshot(scale)
    try:
        data = base64.b64decode(shot.png_base64)
    except (ValueError, TypeError):
        raise CLIError("failed to decode the captured screenshot")
    out_path = args.string(["out", "o"]) or os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "metacua-shot.png"
    )
    path = os.path.expanduser(out_path)
    with open(path, "wb") as handle:
        handle.write(data)
    if shot.image_width == shot.width and shot.image_height == shot.height:
        size_label = f"{shot.image_width}x{shot.image_height}"
    else:
        size_label = (
            f"{shot.image_width}x{shot.image_height} image, {shot.width}x{shot.height} coords"
        )
    print(f"captured {size_label} screenshot -> {path} ({len(data)} bytes)")


def run_move(raw) -> None:
    args = Args(raw)
    x = args.required_double("x")
    y = args.required_double("y")
    app = args.required_string("app")
    point = CGPointMake(x, y)

    _preflight(app)
    move_mouse(point, event_source())
    print(f"moved pointer to ({x}, {y}) in {app}")


def run_scroll(raw) -> None:
    args = Args(raw)
    direction = ScrollDirection.parse(args.required_string("direction"))
    pages = args.int("pages") or 1
    lines_per_page = args.int("lines-per-page") or 10
    app = args.required_string("app")

    x_opt = args.double("x")
    y_opt = args.double("y")
    if (x_opt is None) != (y_opt is None):
        raise CLIError("--x and --y must be provided together", code=2)
    point = None
    if x_opt is not None and y_opt is not None:
        point = CGPointMake(x_opt, y_opt)

    _preflight(app)
    perform_scroll(direction, pages, lines_per_page, point, event_source())
    print(f"scrolled {direction.value} {pages} page(s) in {app}")


def run_drag(raw) -> None:
    args = Args(raw)
    from_x = args.required_double("from-x")
    from_y = args.required_double("from-y")
    to_x = args.required_double("to-x")
    to_y = args.required_double("to-y")
    button = MouseButton.parse(args.string(["mouse-button", "button"]) or "left")
    app = args.required_string("app")
    from_point = CGPointMake(from_x, from_y)
    to_point = CGPointMake(to_x, to_y)

    _preflight(app)
    perform_drag(from_point, to_point, button, event_source())
    print(f"dragged from ({from_x}, {from_y}) to ({to_x}, {to_y}) in {app}")


def run_press_key(raw) -> None:
    args = Args(raw)
    key = args.required_string("key")
    app = args.required_string("app")
    code, flags = parse_key_combo(key)

    _preflight(app)
    perform_key_combo(code, flags, event_source())
    print(f"pressed '{key}' in {app}")


def run_type_text(raw) -> None:
    args = Args(raw)
    text = args.required_string("text")
    app = args.required_string("app")

    _preflight(app)
    perform_type_text(text, event_source())
    print(f"typed {len(text)} character(s) in {app}")
