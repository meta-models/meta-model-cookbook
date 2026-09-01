# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Whole-window ScreenCaptureKit capture for the selected Chess window."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Protocol

from voice_chess_cua.domain.geometry import PixelSize

from ._asyncio import call_soon_threadsafe_if_open
from .application import CHESS_BUNDLE_IDENTIFIER
from .windows import (
    ChessWindowDescriptor,
    ScreenCaptureKitError,
    WindowBackend,
    WindowCandidate,
    _native_error_code,
    _ScreenCaptureKitWindowBackend,
)


class WindowCaptureError(RuntimeError):
    pass


class WindowUnavailableError(WindowCaptureError):
    pass


class InvalidCapturedImageError(WindowCaptureError):
    pass


class WindowCaptureTimedOutError(WindowCaptureError):
    pass


@dataclass
@dataclass(frozen=True, slots=True)
class WindowScreenshot:
    image: object
    window: ChessWindowDescriptor
    image_size: PixelSize
    point_pixel_scale_x: float
    point_pixel_scale_y: float
    captured_at: datetime


class CaptureBackend(Protocol):
    async def capture(self, candidate: WindowCandidate) -> object: ...


class _ScreenCaptureKitCaptureBackend:
    def __init__(self, *, capture_timeout: float = 3.0) -> None:
        if capture_timeout <= 0:
            raise ValueError("capture_timeout must be positive")
        from ._native import load_framework

        self._screen_capture_kit = load_framework("ScreenCaptureKit")
        self._capture_timeout = capture_timeout

    async def capture(self, candidate: WindowCandidate) -> object:
        content = await _ScreenCaptureKitWindowBackend()._shareable_content()
        native_window = next(
            (
                window
                for window in content.windows()
                if _native_window_matches_candidate(window, candidate)
            ),
            None,
        )
        if native_window is None:
            raise WindowUnavailableError(
                f"Window {candidate.window_id} is no longer available for capture"
            )
        filter_ = self._screen_capture_kit.SCContentFilter.alloc().initWithDesktopIndependentWindow_(
            native_window
        )
        configuration = self._screen_capture_kit.SCStreamConfiguration.alloc().init()
        scale = max(float(filter_.pointPixelScale()), 1.0)
        configuration.setWidth_(max(1, ceil(candidate.frame.width * scale)))
        configuration.setHeight_(max(1, ceil(candidate.frame.height * scale)))
        configuration.setShowsCursor_(False)
        configuration.setCapturesAudio_(False)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()

        def completed(image: object | None, error: object | None) -> None:
            def resolve() -> None:
                if future.done():
                    return
                if error is not None:
                    future.set_exception(
                        ScreenCaptureKitError(_native_error_code(error))
                    )
                elif image is None:
                    future.set_exception(
                        InvalidCapturedImageError(
                            "ScreenCaptureKit returned an empty image"
                        )
                    )
                else:
                    future.set_result(image)

            call_soon_threadsafe_if_open(loop, resolve)

        self._screen_capture_kit.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            filter_,
            configuration,
            completed,
        )
        try:
            return await asyncio.wait_for(future, timeout=self._capture_timeout)
        except TimeoutError as error:
            raise WindowCaptureTimedOutError(
                "ScreenCaptureKit window capture timed out"
            ) from error


class WindowScreenshotProvider:
    def __init__(
        self,
        window_backend: WindowBackend | None = None,
        capture_backend: CaptureBackend | None = None,
    ) -> None:
        self._window_backend = window_backend
        self._capture_backend = capture_backend

    @property
    def window_backend(self) -> WindowBackend:
        if self._window_backend is None:
            self._window_backend = _ScreenCaptureKitWindowBackend()
        return self._window_backend

    @property
    def capture_backend(self) -> CaptureBackend:
        if self._capture_backend is None:
            self._capture_backend = _ScreenCaptureKitCaptureBackend()
        return self._capture_backend

    async def capture(self, window_id: int) -> WindowScreenshot:
        candidate = next(
            (
                item
                for item in await self.window_backend.windows()
                if item.window_id == window_id
                and item.is_on_screen
                and item.bundle_identifier == CHESS_BUNDLE_IDENTIFIER
            ),
            None,
        )
        if candidate is None:
            raise WindowUnavailableError(
                f"Window {window_id} is no longer available for capture"
            )
        image = await self.capture_backend.capture(candidate)
        width = _image_dimension(image, "width", "CGImageGetWidth")
        height = _image_dimension(image, "height", "CGImageGetHeight")
        try:
            image_size = PixelSize(width, height)
        except ValueError as error:
            raise InvalidCapturedImageError(
                "ScreenCaptureKit returned an empty image"
            ) from error
        descriptor = ChessWindowDescriptor(
            window_id=candidate.window_id,
            frame=candidate.frame,
            title=candidate.title,
            application_name=candidate.application_name,
            process_id=candidate.process_id,
            is_frontmost=candidate.is_frontmost,
            display_ids=candidate.display_ids,
            bundle_identifier=candidate.bundle_identifier,
        )
        return WindowScreenshot(
            image=image,
            window=descriptor,
            image_size=image_size,
            point_pixel_scale_x=width / candidate.frame.width,
            point_pixel_scale_y=height / candidate.frame.height,
            captured_at=datetime.now(UTC),
        )


def _native_window_matches_candidate(
    window: object, candidate: WindowCandidate
) -> bool:
    try:
        application = window.owningApplication()  # type: ignore[attr-defined]
        return bool(
            application is not None
            and int(window.windowID()) == candidate.window_id  # type: ignore[attr-defined]
            and bool(window.isOnScreen())  # type: ignore[attr-defined]
            and str(application.bundleIdentifier() or "") == CHESS_BUNDLE_IDENTIFIER
            and int(application.processID()) == candidate.process_id
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _image_dimension(image: object, name: str, quartz_function: str) -> int:
    value = getattr(image, name, None)
    if callable(value):
        value = value()
    if value is None:
        from ._native import load_framework

        value = getattr(load_framework("Quartz"), quartz_function)(image)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidCapturedImageError("ScreenCaptureKit returned an invalid image")
    return int(value)
