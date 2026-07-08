"""Accessibility and Screen Recording permission checks."""

import sys

from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

from .args import Args
from .errors import CLIError


def is_trusted() -> bool:
    """Whether the controlling process is trusted for Accessibility, required for
    CGEventPost to actually deliver synthetic events.
    """
    return bool(AXIsProcessTrusted())


def has_screen_recording_access() -> bool:
    """Whether the process can capture the screen (required for screenshots)."""
    return bool(CGPreflightScreenCaptureAccess())


def ensure_screen_recording(prompt: bool) -> bool:
    """True if screen capture is allowed; when `prompt` and not yet allowed, asks
    the system to surface the Screen Recording dialog.
    """
    if CGPreflightScreenCaptureAccess():
        return True
    if prompt:
        return bool(CGRequestScreenCaptureAccess())
    return False


def require_screen_recording() -> None:
    if not ensure_screen_recording(prompt=False):
        raise CLIError(
            "Screen Recording permission is not granted, so screenshots would be "
            "blank. Enable your terminal (or the metacua binary) under System Settings "
            "→ Privacy & Security → Screen Recording, then retry. "
            "Run `metacua permissions --prompt` to open the system dialog.",
            code=3,
        )


def ensure_trusted(prompt: bool) -> bool:
    """True if trusted. When `prompt` and not yet trusted, asks the system to show
    the "grant Accessibility access" dialog.
    """
    if AXIsProcessTrusted():
        return True
    if prompt:
        # Key string is stable across SDKs; avoids Unmanaged<CFString> import quirks.
        options = {"AXTrustedCheckOptionPrompt": True}
        return bool(AXIsProcessTrustedWithOptions(options))
    return False


def require_trust() -> None:
    if not ensure_trusted(prompt=False):
        raise CLIError(
            "Accessibility permission is not granted, so synthetic events would be "
            "silently dropped. Enable your terminal (or the metacua binary) under "
            "System Settings → Privacy & Security → Accessibility, then retry. "
            "Run `metacua permissions --prompt` to open the system dialog.",
            code=3,
        )


def run_permissions(raw) -> None:
    args = Args(raw)
    wants_prompt = args.flag("prompt")

    trusted = ensure_trusted(prompt=wants_prompt)
    screen = ensure_screen_recording(prompt=wants_prompt)

    print(
        f"Accessibility:    {'GRANTED' if trusted else 'NOT granted'} — "
        "needed to post mouse/keyboard events"
    )
    print(
        f"Screen Recording: {'GRANTED' if screen else 'NOT granted'} — "
        "needed for the agent to take screenshots"
    )

    if not trusted or not screen:
        print("")
        print("Grant the missing permission(s) to your terminal (or the metacua binary) under")
        print("System Settings → Privacy & Security → {Accessibility, Screen Recording}.")
        if wants_prompt:
            print("A system dialog was requested where possible; grant access, then re-run.")
        else:
            print("Run `metacua permissions --prompt` to open the system dialog(s).")
        sys.exit(3)
    print("\nAll set — `metacua agent` is ready to run.")
