# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""ScreenCaptureKit discovery for one exact, visible Apple Chess window."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from voice_chess_cua.domain.geometry import Rect

from .application import CHESS_BUNDLE_IDENTIFIER
from .native import call_soon_threadsafe_if_open


class ChessWindowError(RuntimeError):
    pass


class NoVisibleChessWindowError(ChessWindowError):
    pass


class ShareableContentTimedOutError(ChessWindowError):
    pass


class ScreenCaptureKitError(ChessWindowError):
    def __init__(self, code: int | None) -> None:
        self.code = code
        super().__init__("ScreenCaptureKit operation failed")


class AmbiguousChessWindowError(ChessWindowError):
    def __init__(self, window_ids: Iterable[int]) -> None:
        self.window_ids = tuple(window_ids)
        super().__init__(
            "Multiple visible Apple Chess windows were found: "
            + ", ".join(str(window_id) for window_id in self.window_ids)
        )


@dataclass(frozen=True, slots=True)
class ChessWindowDescriptor:
    window_id: int
    frame: Rect
    title: str | None
    application_name: str
    process_id: int
    bundle_identifier: str = CHESS_BUNDLE_IDENTIFIER


@dataclass(frozen=True, slots=True)
class WindowCandidate:
    window_id: int
    frame: Rect
    title: str | None
    application_name: str
    process_id: int
    bundle_identifier: str
    is_on_screen: bool


class WindowBackend(Protocol):
    async def windows(self) -> tuple[WindowCandidate, ...]: ...


class _ScreenCaptureKitWindowBackend:
    def __init__(self, *, shareable_content_timeout: float = 3.0) -> None:
        if shareable_content_timeout <= 0:
            raise ValueError("shareable_content_timeout must be positive")
        from .native import load_framework

        self._screen_capture_kit = load_framework("ScreenCaptureKit")
        self._shareable_content_timeout = shareable_content_timeout

    async def windows(self) -> tuple[WindowCandidate, ...]:
        content = await self._shareable_content()
        candidates: list[WindowCandidate] = []
        for window in content.windows():
            application = window.owningApplication()
            if application is None:
                continue
            frame = _rect_from_native(window.frame())
            candidates.append(
                WindowCandidate(
                    window_id=int(window.windowID()),
                    frame=frame,
                    title=window.title(),
                    application_name=str(application.applicationName() or ""),
                    process_id=int(application.processID()),
                    bundle_identifier=str(application.bundleIdentifier() or ""),
                    is_on_screen=bool(window.isOnScreen()),
                )
            )
        return tuple(candidates)

    async def _shareable_content(self) -> Any:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def completed(content: object | None, error: object | None) -> None:
            def resolve() -> None:
                if future.done():
                    return
                if error is not None:
                    future.set_exception(
                        ScreenCaptureKitError(_native_error_code(error))
                    )
                elif content is None:
                    future.set_exception(
                        RuntimeError("ScreenCaptureKit returned no content")
                    )
                else:
                    future.set_result(content)

            call_soon_threadsafe_if_open(loop, resolve)

        self._screen_capture_kit.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            False,
            True,
            completed,
        )
        try:
            return await asyncio.wait_for(
                future,
                timeout=self._shareable_content_timeout,
            )
        except TimeoutError as error:
            raise ShareableContentTimedOutError(
                "ScreenCaptureKit window discovery timed out"
            ) from error


def _native_error_code(error: object) -> int | None:
    code = getattr(error, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:  # noqa: BLE001 - native diagnostics remain best-effort.
            return None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


class ChessWindowLocator:
    def __init__(self, backend: WindowBackend | None = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> WindowBackend:
        if self._backend is None:
            self._backend = _ScreenCaptureKitWindowBackend()
        return self._backend

    async def locate(
        self, expected_process_id: int | None = None
    ) -> ChessWindowDescriptor:
        if expected_process_id is not None and not _is_positive_identifier(
            expected_process_id
        ):
            raise ValueError("expected_process_id must be a positive integer")
        eligible = tuple(
            candidate
            for candidate in await self.backend.windows()
            if candidate.bundle_identifier == CHESS_BUNDLE_IDENTIFIER
            and candidate.is_on_screen
            and _is_positive_identifier(candidate.process_id)
            and (
                expected_process_id is None
                or candidate.process_id == expected_process_id
            )
        )
        if not eligible:
            raise NoVisibleChessWindowError("No visible Apple Chess window was found")
        if len(eligible) != 1:
            raise AmbiguousChessWindowError(
                candidate.window_id for candidate in eligible
            )
        selected = eligible[0]
        return ChessWindowDescriptor(
            window_id=selected.window_id,
            frame=selected.frame,
            title=selected.title,
            application_name=selected.application_name,
            process_id=selected.process_id,
            bundle_identifier=selected.bundle_identifier,
        )


def _is_positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _rect_from_native(rect: Any) -> Rect:
    try:
        return Rect(
            float(rect.origin.x),
            float(rect.origin.y),
            float(rect.size.width),
            float(rect.size.height),
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise ChessWindowError(
            "Apple Chess reported an invalid window frame"
        ) from error
