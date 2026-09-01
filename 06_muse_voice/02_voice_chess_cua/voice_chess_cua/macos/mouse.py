# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Serialized, fail-closed Core Graphics input posting for Apple Chess."""

from __future__ import annotations

import asyncio
from math import isfinite
from typing import Any, Protocol

from voice_chess_cua.domain.geometry import Point

from .application import CHESS_BUNDLE_IDENTIFIER


class EventPosterError(RuntimeError):
    pass


class EventSourceUnavailableError(EventPosterError):
    pass


class EventCreationFailedError(EventPosterError):
    pass


class EventTargetChangedError(EventPosterError):
    pass


class EventPairPartiallyPostedError(EventPosterError):
    """The down event was posted, and release was attempted but did not complete."""


class EventBackend(Protocol):
    def create_source(self) -> object | None: ...

    def click_events(
        self, source: object, point: Point
    ) -> tuple[object | None, object | None]: ...

    def target_is_frontmost(self, process_identifier: int) -> bool: ...

    def post(self, event: object) -> None: ...


class _QuartzEventBackend:
    def __init__(self) -> None:
        from ._native import load_framework

        self._appkit = load_framework("AppKit")
        self._quartz = load_framework("Quartz")

    def create_source(self) -> Any:
        return self._quartz.CGEventSourceCreate(
            self._quartz.kCGEventSourceStateCombinedSessionState
        )

    def click_events(
        self,
        source: object,
        point: Point,
    ) -> tuple[object | None, object | None]:
        location = self._quartz.CGPointMake(point.x, point.y)
        return (
            self._quartz.CGEventCreateMouseEvent(
                source,
                self._quartz.kCGEventLeftMouseDown,
                location,
                self._quartz.kCGMouseButtonLeft,
            ),
            self._quartz.CGEventCreateMouseEvent(
                source,
                self._quartz.kCGEventLeftMouseUp,
                location,
                self._quartz.kCGMouseButtonLeft,
            ),
        )

    def target_is_frontmost(self, process_identifier: int) -> bool:
        frontmost = self._appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return bool(
            frontmost is not None
            and int(frontmost.processIdentifier()) == process_identifier
            and str(frontmost.bundleIdentifier() or "") == CHESS_BUNDLE_IDENTIFIER
        )

    def post(self, event: object) -> None:
        self._quartz.CGEventPost(self._quartz.kCGHIDEventTap, event)


class CGEventPoster:
    def __init__(self, backend: EventBackend | None = None) -> None:
        self._backend = backend
        self._operation_lock = asyncio.Lock()

    @property
    def backend(self) -> EventBackend:
        if self._backend is None:
            self._backend = _QuartzEventBackend()
        return self._backend

    async def click(self, point: Point, process_identifier: int) -> None:
        if (
            not isinstance(point, Point)
            or not isfinite(point.x)
            or not isfinite(point.y)
        ):
            raise EventCreationFailedError(
                "macOS could not create the requested input event."
            )
        if process_identifier <= 0:
            raise EventCreationFailedError(
                "A valid Chess process identifier is required."
            )
        async with self._operation_lock:
            await asyncio.to_thread(self._post_click, point, process_identifier)

    def _post_click(self, point: Point, process_identifier: int) -> None:
        source = self.backend.create_source()
        if source is None:
            raise EventSourceUnavailableError(
                "macOS could not create a trusted input event source."
            )
        down, up = self.backend.click_events(source, point)
        self._post_pair(process_identifier, down, up)

    def _post_pair(
        self,
        process_identifier: int,
        down: object | None,
        up: object | None,
    ) -> None:
        if down is None or up is None:
            raise EventCreationFailedError(
                "macOS could not create the requested input event."
            )
        if not self.backend.target_is_frontmost(process_identifier):
            raise EventTargetChangedError(
                "Apple Chess is no longer the exact frontmost process."
            )
        self.backend.post(down)
        try:
            self.backend.post(up)
        except Exception as error:
            try:
                self.backend.post(up)
            except Exception:  # noqa: BLE001, S110 - best-effort release after partial post.
                pass
            raise EventPairPartiallyPostedError(
                "The input down event was posted but release could not be confirmed."
            ) from error
