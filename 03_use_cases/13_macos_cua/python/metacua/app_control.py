"""Bring a named application to the front before events are posted."""

import subprocess
import time
from typing import Optional

from AppKit import (
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyRegular,
    NSWorkspace,
)

from .errors import CLIError

# Identifiers that mean "act on whatever app is already frontmost".
_PASSTHROUGH_IDENTIFIERS = {"current", "frontmost", "-", "active"}


def activate_app(identifier: str) -> None:
    """Bring the named application to the front.

    `identifier` may be a bundle id (`com.apple.Safari`), an exact localized name
    (`Safari`), or a case-insensitive substring of one. If not running, a launch
    is attempted via `open -a`. Returns once the app reports itself active, or
    after a short timeout.
    """
    if identifier.lower() in _PASSTHROUGH_IDENTIFIERS:
        return

    app = _find_running_app(identifier)
    if app is None:
        _launch_app(identifier)
        # Poll for the freshly launched process to appear.
        deadline = time.time() + 8.0
        while app is None and time.time() < deadline:
            time.sleep(0.15)
            app = _find_running_app(identifier)

    if app is None:
        raise CLIError(f"application not found and could not be launched: '{identifier}'")

    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

    # Wait for the app to actually become frontmost so events land in it.
    deadline = time.time() + 3.0
    while not app.isActive() and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.12)  # brief settle so the window is ready for input


def _find_running_app(identifier: str):
    needle = identifier.lower()
    all_apps = NSWorkspace.sharedWorkspace().runningApplications()

    # Exact bundle id is an unambiguous, explicit selector — allow any policy.
    for app in all_apps:
        bundle = app.bundleIdentifier()
        if bundle is not None and bundle.lower() == needle:
            return app

    # Name / substring should resolve to a user-facing (.regular) app so a
    # background/accessory agent is never chosen as the activation target.
    regular = [a for a in all_apps if a.activationPolicy() == NSApplicationActivationPolicyRegular]
    for app in regular:
        name = app.localizedName()
        if name is not None and name.lower() == needle:
            return app
    for app in regular:
        name = app.localizedName()
        if name is not None and needle in name.lower():
            return app
    return None


def _looks_like_bundle_id(identifier: str) -> bool:
    """Heuristic: a reverse-DNS identifier (contains a dot, no spaces) is a bundle id."""
    return "." in identifier and " " not in identifier


def _launch_app(identifier: str) -> None:
    # `open -a` takes an application NAME or path; bundle ids must use `-b`.
    args = ["-b", identifier] if _looks_like_bundle_id(identifier) else ["-a", identifier]
    try:
        proc = subprocess.run(["/usr/bin/open", *args], capture_output=True)
    except OSError as exc:
        raise CLIError(f"failed to launch '{identifier}': {exc}")
    if proc.returncode != 0:
        raise CLIError(
            f"application not found and could not be launched: '{identifier}' "
            "(launch requires an exact app name or bundle id)"
        )
