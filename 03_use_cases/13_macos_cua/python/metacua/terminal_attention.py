"""Ring the bell and reactivate the launching terminal when a goal ends."""

import os
import subprocess
import sys
from typing import Optional, Set

try:
    from AppKit import NSRunningApplication, NSWorkspace
    from AppKit import NSApplicationActivationPolicyRegular

    _HAS_APPKIT = True
except ImportError:  # pragma: no cover
    _HAS_APPKIT = False


class TerminalAttention:
    def __init__(self, enabled: Optional[bool] = None):
        self._enabled = sys.stdout.isatty() if enabled is None else enabled
        self._terminal_app = self._find_launching_terminal_app() if self._enabled else None

    def wake(self) -> bool:
        if not self._enabled:
            return False
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        if self._terminal_app is None:
            return False
        try:
            # Newer macOS uses the no-argument activate(); options-based activation
            # remains available as a fallback.
            if hasattr(self._terminal_app, "activate"):
                self._terminal_app.activate()
            else:  # pragma: no cover
                self._terminal_app.activateWithOptions_(1)
        except Exception:  # noqa: BLE001
            return False
        return True

    def _find_launching_terminal_app(self):
        if not _HAS_APPKIT:
            return None
        pid = os.getppid()
        seen: Set[int] = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if app is not None and app.activationPolicy() == NSApplicationActivationPolicyRegular:
                return app
            parent = self._parent_process_id(pid)
            if parent is None or parent == pid:
                break
            pid = parent
        return self._fallback_terminal_app()

    @staticmethod
    def _parent_process_id(pid: int) -> Optional[int]:
        try:
            out = subprocess.run(
                ["/bin/ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        raw = out.stdout.strip()
        try:
            return int(raw)
        except ValueError:
            return None

    def _fallback_terminal_app(self):
        candidates = self._terminal_app_name_candidates()
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.activationPolicy() != NSApplicationActivationPolicyRegular:
                continue
            name = app.localizedName()
            if name in candidates:
                return app
        return None

    @staticmethod
    def _terminal_app_name_candidates() -> Set[str]:
        term = os.environ.get("TERM_PROGRAM")
        if term == "Apple_Terminal":
            return {"Terminal"}
        if term == "iTerm.app":
            return {"iTerm", "iTerm2"}
        if term == "vscode":
            return {"Visual Studio Code", "VS Code"}
        if term == "WezTerm":
            return {"WezTerm"}
        if term == "WarpTerminal":
            return {"Warp"}
        return {"Terminal", "iTerm", "iTerm2", "Visual Studio Code", "VS Code"}
