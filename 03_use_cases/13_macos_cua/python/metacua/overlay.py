"""Transparent, click-through cursor overlay driven with CoreAnimation.

Renders a small glowing animated cursor at each action the agent performs so the
user can watch the model drive the machine. All public methods are thread-safe
(they hop to the main thread); the agent loop calls them from its background thread.
"""

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSView,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakeRect, NSMakePoint, NSObject
from Quartz import (
    CABasicAnimation,
    CAKeyframeAnimation,
    CALayer,
    CAMediaTimingFunction,
    CAShapeLayer,
    CATextLayer,
    CATransaction,
    CGPathCreateWithEllipseInRect,
    CGPointMake,
    CGRectMake,
    CGShieldingWindowLevel,
    kCAMediaTimingFunctionEaseInEaseOut,
    kCAMediaTimingFunctionEaseOut,
)
import Quartz

from .screenshot import primary_screen

# NSWindow collection-behavior flags (not all are exported by name in pyobjc).
_CAN_JOIN_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4
_FULLSCREEN_AUXILIARY = 1 << 8
_IGNORES_CYCLE = 1 << 6


def dispatch_main(work):
    """Run `work` on the main thread asynchronously."""
    from Foundation import NSOperationQueue

    NSOperationQueue.mainQueue().addOperationWithBlock_(work)


class OverlayController:
    # A warm rose accent (not blue), with a soft glow.
    _accent = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.36, 0.52, 1.0)
    _radius = 13.0  # smaller cursor
    _hold_seconds = 1.1  # linger after the last action
    _fade_seconds = 0.45

    def __init__(self):
        self._window = None
        self._host_layer = None
        self._cursor_layer = None
        self._label_container = None
        self._label_text = None
        self._screen_height = 0.0
        self._hide_timer = None

        screen = primary_screen()
        if screen is None:
            return
        frame = screen.frame()
        self._screen_height = frame.size.height

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(False)
        window.setIgnoresMouseEvents_(True)
        window.setLevel_(int(CGShieldingWindowLevel()))
        window.setCollectionBehavior_(
            _CAN_JOIN_ALL_SPACES | _STATIONARY | _FULLSCREEN_AUXILIARY | _IGNORES_CYCLE
        )

        view = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, frame.size.width, frame.size.height)
        )
        view.setWantsLayer_(True)
        host = CALayer.layer()
        host.setFrame_(view.bounds())
        view.setLayer_(host)
        window.setContentView_(view)

        scale = screen.backingScaleFactor()

        # Cursor group: glowing ring + center dot, anchored at its center.
        cursor = CALayer.layer()
        d = self._radius * 2
        cursor.setBounds_(CGRectMake(0, 0, d, d))
        cursor.setOpacity_(0)  # hidden until the first action

        ring = CAShapeLayer.layer()
        ring.setPath_(CGPathCreateWithEllipseInRect(CGRectMake(1.5, 1.5, d - 3, d - 3), None))
        ring.setFillColor_(self._accent.colorWithAlphaComponent_(0.12).CGColor())
        ring.setStrokeColor_(self._accent.CGColor())
        ring.setLineWidth_(2)
        ring.setShadowColor_(self._accent.CGColor())
        ring.setShadowRadius_(7)
        ring.setShadowOpacity_(0.85)
        ring.setShadowOffset_(Quartz.CGSizeMake(0, 0))
        ring.setFrame_(cursor.bounds())
        cursor.addSublayer_(ring)

        dot = CAShapeLayer.layer()
        dot_r = 3.0
        dot.setPath_(
            CGPathCreateWithEllipseInRect(
                CGRectMake(self._radius - dot_r, self._radius - dot_r, dot_r * 2, dot_r * 2), None
            )
        )
        dot.setFillColor_(self._accent.CGColor())
        dot.setFrame_(cursor.bounds())
        cursor.addSublayer_(dot)

        host.addSublayer_(cursor)

        # Action label pill below the cursor.
        pill = CALayer.layer()
        pill.setBackgroundColor_(NSColor.blackColor().colorWithAlphaComponent_(0.68).CGColor())
        pill.setCornerRadius_(8)
        pill.setOpacity_(0)
        text = CATextLayer.layer()
        text.setFontSize_(11)
        text.setForegroundColor_(NSColor.whiteColor().CGColor())
        text.setAlignmentMode_("center")
        text.setTruncationMode_("end")
        text.setContentsScale_(scale)
        pill.addSublayer_(text)
        host.addSublayer_(pill)

        self._window = window
        self._host_layer = host
        self._cursor_layer = cursor
        self._label_container = pill
        self._label_text = text

        window.orderFrontRegardless()

    # MARK: - Public API (global top-left coordinates)

    def show_action(self, label, point):
        def work():
            self._place_cursor(point, True, label)
            self._schedule_hide()

        self._on_main(work)

    def show_click(self, label, point):
        def work():
            self._place_cursor(point, True, label)
            self._ripple(point)
            self._bounce()
            self._schedule_hide()

        self._on_main(work)

    def show_drag(self, label, from_point, to_point, duration):
        def work():
            self._place_cursor(from_point, True, label)
            self._ripple(from_point)
            self._place_cursor(to_point, True, label, max(0.2, duration))
            self._schedule_hide()

        self._on_main(work)

    # MARK: - Internals (main thread only)

    def _place_cursor(self, point, animated, label, duration=0.22):
        cursor = self._cursor_layer
        if cursor is None:
            return
        self._cancel_hide()
        p = self._to_view(point)

        CATransaction.begin()
        CATransaction.setAnimationDuration_(duration if animated else 0)
        CATransaction.setAnimationTimingFunction_(
            CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut)
        )
        cursor.setPosition_(p)
        cursor.setOpacity_(1)
        self._position_label(p)
        CATransaction.commit()

        self._set_label(label)

    def _position_label(self, p):
        pill = self._label_container
        text = self._label_text
        if pill is None or text is None:
            return
        width = 170.0
        height = 18.0
        pill.setBounds_(CGRectMake(0, 0, width, height))
        pill.setPosition_(CGPointMake(p.x, p.y - self._radius - 15))
        text.setFrame_(CGRectMake(7, 2, width - 14, height - 4))

    def _set_label(self, label):
        pill = self._label_container
        text = self._label_text
        if pill is None or text is None:
            return
        text.setString_(label)
        pill.setOpacity_(0 if not label else 1)

    def _ripple(self, point):
        host = self._host_layer
        if host is None:
            return
        p = self._to_view(point)
        d = self._radius * 2.2
        ripple = CAShapeLayer.layer()
        ripple.setPath_(CGPathCreateWithEllipseInRect(CGRectMake(0, 0, d, d), None))
        ripple.setBounds_(CGRectMake(0, 0, d, d))
        ripple.setPosition_(p)
        ripple.setFillColor_(NSColor.clearColor().CGColor())
        ripple.setStrokeColor_(self._accent.CGColor())
        ripple.setLineWidth_(2)
        host.addSublayer_(ripple)

        scale = CABasicAnimation.animationWithKeyPath_("transform.scale")
        scale.setFromValue_(0.4)
        scale.setToValue_(1.7)
        fade = CABasicAnimation.animationWithKeyPath_("opacity")
        fade.setFromValue_(0.85)
        fade.setToValue_(0)
        group = Quartz.CAAnimationGroup.animation()
        group.setAnimations_([scale, fade])
        group.setDuration_(0.5)
        group.setTimingFunction_(CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseOut))
        group.setRemovedOnCompletion_(True)
        ripple.setOpacity_(0)
        ripple.addAnimation_forKey_(group, "ripple")

        self._after(0.55, lambda: ripple.removeFromSuperlayer())

    def _bounce(self):
        cursor = self._cursor_layer
        if cursor is None:
            return
        bounce = CAKeyframeAnimation.animationWithKeyPath_("transform.scale")
        bounce.setValues_([1.0, 0.82, 1.0])
        bounce.setKeyTimes_([0, 0.4, 1.0])
        bounce.setDuration_(0.26)
        bounce.setTimingFunction_(CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseOut))
        cursor.addAnimation_forKey_(bounce, "bounce")

    def _cancel_hide(self):
        if self._hide_timer is not None:
            self._hide_timer.invalidate()
            self._hide_timer = None
        if self._cursor_layer is not None:
            self._cursor_layer.removeAnimationForKey_("hide")
        if self._label_container is not None:
            self._label_container.removeAnimationForKey_("hide")

    def _schedule_hide(self):
        if self._hide_timer is not None:
            self._hide_timer.invalidate()
        self._hide_timer = self._after(self._hold_seconds, self._fade_out)

    def _fade_out(self):
        for layer in (self._cursor_layer, self._label_container):
            if layer is None:
                continue
            fade = CABasicAnimation.animationWithKeyPath_("opacity")
            presentation = layer.presentationLayer()
            fade.setFromValue_(presentation.opacity() if presentation is not None else layer.opacity())
            fade.setToValue_(0)
            fade.setDuration_(self._fade_seconds)
            fade.setTimingFunction_(CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseOut))
            fade.setFillMode_("forwards")
            fade.setRemovedOnCompletion_(False)
            layer.addAnimation_forKey_(fade, "hide")
            layer.setOpacity_(0)

    def _to_view(self, p):
        return CGPointMake(p.x, self._screen_height - p.y)

    def _on_main(self, work):
        from Foundation import NSThread

        if NSThread.isMainThread():
            work()
        else:
            dispatch_main(work)

    def _after(self, seconds, work):
        """Schedule `work` on the main run loop after `seconds`; returns an NSTimer."""
        from Foundation import NSTimer

        holder = {}

        def handler(timer):
            work()

        timer = NSTimer.timerWithTimeInterval_repeats_block_(seconds, False, handler)
        from Foundation import NSRunLoop, NSDefaultRunLoopMode

        NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSDefaultRunLoopMode)
        return timer
