"""Screen capture, downscaled to logical points.

A pixel (x, y) in the returned image equals a CGEvent global coordinate (x, y),
so the agent's coordinates map 1:1 onto the cursor position on Retina displays.
"""

import base64
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from AppKit import (
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSDeviceRGBColorSpace,
    NSGraphicsContext,
    NSImageInterpolationHigh,
    NSRectFill,
    NSScreen,
)
from Foundation import NSData, NSMakeRect, NSMakeSize
from Quartz import CGDisplayBounds, CGMainDisplayID

from .errors import CLIError
from .letterbox import fit_transform


@dataclass
class Screenshot:
    """A captured screen image plus the logical coordinate space it represents."""

    png_base64: str
    width: int  # logical points - the coordinate space the agent operates in
    height: int
    image_width: int
    image_height: int


def primary_screen() -> Optional["NSScreen"]:
    """The primary display whose top-left is the global coordinate origin."""
    screens = NSScreen.screens()
    return screens[0] if screens and len(screens) else None


def _redraw_png(source: "NSBitmapImageRep", width: int, height: int) -> bytes:
    """Redraw a bitmap into a fresh RGBA bitmap of `width`x`height` and PNG-encode it."""
    scaled = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, width, height, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0,
    )
    if scaled is None:
        raise CLIError("could not allocate a bitmap for scaling")
    scaled.setSize_(NSMakeSize(width, height))

    NSGraphicsContext.saveGraphicsState()
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(scaled)
    NSGraphicsContext.setCurrentContext_(context)
    if context is not None:
        context.setImageInterpolation_(NSImageInterpolationHigh)
    source.drawInRect_(NSMakeRect(0, 0, width, height))
    NSGraphicsContext.restoreGraphicsState()

    png = scaled.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    if png is None:
        raise CLIError("could not re-encode the screenshot as PNG")
    return bytes(png)


def scaled_letterboxed_png_base64(shot: "Screenshot", width: int, height: int):
    """Aspect-fit `shot` into a black `width`x`height` PNG and return (b64, fit)."""
    fit = fit_transform(shot.width, shot.height, width, height)
    raw_bytes = base64.b64decode(shot.png_base64)
    data = NSData.dataWithBytes_length_(raw_bytes, len(raw_bytes))
    source = NSBitmapImageRep.alloc().initWithData_(data)
    if source is None:
        raise CLIError("could not decode the screenshot for scaling")

    scaled = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, width, height, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0,
    )
    if scaled is None:
        raise CLIError("could not allocate a bitmap for scaling")
    scaled.setSize_(NSMakeSize(width, height))

    NSGraphicsContext.saveGraphicsState()
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(scaled)
    NSGraphicsContext.setCurrentContext_(context)
    if context is not None:
        context.setImageInterpolation_(NSImageInterpolationHigh)
    NSColor.blackColor().setFill()
    # AppKit drawing uses a bottom-left origin in this bitmap context. Centering
    # is symmetric, so the same offsets describe the letterbox transform.
    NSRectFill(NSMakeRect(0, 0, width, height))
    source.drawInRect_(NSMakeRect(fit.ox, fit.oy, fit.drawn_w, fit.drawn_h))
    NSGraphicsContext.restoreGraphicsState()

    png = scaled.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    if png is None:
        raise CLIError("could not re-encode the screenshot as PNG")
    return base64.b64encode(bytes(png)).decode("ascii"), fit


def capture_screenshot(scale: float = 1.0) -> Screenshot:
    """Capture the primary display, encoding a possibly downsampled image.

    The full logical display coordinate space is retained for CGEvent actions.
    Uses `screencapture` (requires Screen Recording permission) to avoid the
    deprecated CGDisplayCreateImage path.
    """
    # CGDisplayBounds is thread-safe (this runs on the agent's background thread,
    # where NSScreen would be unsafe). Its size is in logical points, matching the
    # CGEvent global coordinate space the agent operates in.
    bounds = CGDisplayBounds(CGMainDisplayID())
    logical_width = int(round(bounds.size.width))
    logical_height = int(round(bounds.size.height))
    if logical_width <= 0 or logical_height <= 0:
        raise CLIError("no display found to capture")
    if not math.isfinite(scale) or scale <= 0 or scale > 1:
        raise CLIError(f"screenshot scale must be > 0 and <= 1 (got {scale})", code=2)
    image_width = max(1, int(round(logical_width * scale)))
    image_height = max(1, int(round(logical_height * scale)))

    fd, tmp = tempfile.mkstemp(prefix=f"metacua-{os.getpid()}-", suffix="-shot.png")
    os.close(fd)
    try:
        # -x: no capture sound, -t png, -D 1: main display.
        proc = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-t", "png", "-D", "1", tmp],
            capture_output=True,
        )
        if proc.returncode != 0 or not os.path.exists(tmp):
            raise CLIError(
                f"screencapture failed (status {proc.returncode}). "
                "Grant Screen Recording permission and retry."
            )
        raw = NSData.dataWithContentsOfFile_(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    if raw is None:
        raise CLIError("screencapture produced no output; grant Screen Recording permission.")

    source = NSBitmapImageRep.alloc().initWithData_(raw)
    if source is None:
        raise CLIError("could not decode the captured screenshot")

    # Downscale into a fresh RGBA bitmap. The encoded image may be lower
    # resolution than the logical coordinate space used for actions.
    png = _redraw_png(source, image_width, image_height)

    return Screenshot(
        png_base64=base64.b64encode(png).decode("ascii"),
        width=logical_width,
        height=logical_height,
        image_width=image_width,
        image_height=image_height,
    )
