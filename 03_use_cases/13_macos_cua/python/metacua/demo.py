"""`metacua demo` - preview the cursor overlay and smooth movement without an LLM.

It glides the real cursor and plays the click/type/drag effects at a few screen
points; it does NOT click, type, or drag anything (no app is touched).
"""

import threading
import time

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from Quartz import CGPointMake

from .errors import CLIError
from .mouse import event_source, smooth_move
from .overlay import OverlayController, dispatch_main
from .permissions import require_trust
from .screenshot import primary_screen


def run_demo(raw) -> None:
    require_trust()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    overlay = OverlayController()
    src = event_source()

    screen = primary_screen()
    if screen is None:
        raise CLIError("no display found")
    frame = screen.frame()
    w = frame.size.width
    h = frame.size.height

    def pt(fx, fy):
        return CGPointMake(w * fx, h * fy)

    def worker():
        # Two quick clicks — the cursor stays visible across rapid actions.
        a = pt(0.34, 0.34)
        smooth_move(a, src)
        overlay.show_click("click", a)
        time.sleep(0.65)
        b = pt(0.6, 0.44)
        smooth_move(b, src)
        overlay.show_click("double-click", b)
        time.sleep(0.65)

        # Pause long enough to watch it linger, then fade out…
        time.sleep(2.2)

        # …then reappear for a type label.
        c = pt(0.45, 0.6)
        smooth_move(c, src)
        overlay.show_action("type: hello world", c)
        time.sleep(1.9)

        # A drag (overlay + real cursor glide only — nothing is actually dragged).
        from_point = pt(0.3, 0.7)
        to_point = pt(0.62, 0.72)
        smooth_move(from_point, src)
        overlay.show_drag("drag", from_point, to_point, 0.6)
        smooth_move(to_point, src)
        time.sleep(2.2)

        dispatch_main(lambda: app.terminate_(None))

    threading.Thread(target=worker, daemon=True).start()
    app.run()
