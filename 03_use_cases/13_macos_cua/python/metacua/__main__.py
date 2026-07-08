"""Entry point. Dispatches the first argument to a subcommand.

Pure-GUI automation: every action is driven by pixel coordinates and synthetic
keyboard/mouse events (CGEvent). `--app` is used only to bring the target
application to the front before the action is performed.
"""

import sys

from . import __version__
from .args import print_usage
from .errors import CLIError


def _ensure_macos() -> None:
    if sys.platform != "darwin":
        sys.stderr.write(
            "error: metacua drives macOS natively (CGEvent/AppKit) and only runs on macOS\n"
        )
        sys.exit(2)


def main() -> None:
    argv = sys.argv[1:]

    try:
        if not argv:
            _ensure_macos()
            from .agent import run_agent

            run_agent([])
            sys.exit(0)

        command = argv[0]
        rest = argv[1:]

        if command in ("-h", "--help", "help"):
            print_usage()
            return
        if command in ("-v", "--version", "version"):
            print(f"metacua {__version__}")
            return

        known_commands = {
            "click", "moveto", "move", "pointer", "cursor", "shot", "screenshot",
            "demo", "overlay-demo", "scroll", "drag", "press-key", "press_key",
            "key", "type-text", "type_text", "type", "agent", "sessions",
            "session-history", "history", "configure", "config", "permissions",
            "perm", "check",
        }
        if command not in known_commands:
            sys.stderr.write(f"error: unknown command '{command}'\n\n")
            print_usage(to_stderr=True)
            sys.exit(2)

        _ensure_macos()

        if command == "click":
            from .commands import run_click

            run_click(rest)
        elif command in ("moveto", "move"):
            from .commands import run_move

            run_move(rest)
        elif command in ("pointer", "cursor"):
            from .pointer import run_pointer_control

            run_pointer_control(rest)
        elif command in ("shot", "screenshot"):
            from .commands import run_shot

            run_shot(rest)
        elif command in ("demo", "overlay-demo"):
            from .demo import run_demo

            run_demo(rest)
        elif command == "scroll":
            from .commands import run_scroll

            run_scroll(rest)
        elif command == "drag":
            from .commands import run_drag

            run_drag(rest)
        elif command in ("press-key", "press_key", "key"):
            from .commands import run_press_key

            run_press_key(rest)
        elif command in ("type-text", "type_text", "type"):
            from .commands import run_type_text

            run_type_text(rest)
        elif command == "agent":
            from .agent import run_agent

            run_agent(rest)
        elif command in ("sessions", "session-history", "history"):
            from .session_store import run_sessions

            run_sessions(rest)
        elif command in ("configure", "config"):
            from .config import run_configure

            run_configure(rest)
        elif command in ("permissions", "perm", "check"):
            from .permissions import run_permissions

            run_permissions(rest)
    except CLIError as error:
        sys.stderr.write(f"error: {error.message}\n")
        sys.exit(error.code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
