# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Exact Apple Chess activation and status adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ._main_thread import run_on_main

CHESS_BUNDLE_IDENTIFIER = "com.apple.Chess"


class ChessApplicationError(RuntimeError):
    pass


class ChessApplicationUnavailableError(ChessApplicationError):
    pass


class ChessApplicationAmbiguousError(ChessApplicationError):
    pass


class ChessActivationTimedOutError(ChessApplicationError):
    pass


@dataclass(frozen=True, slots=True)
class ChessApplicationStatus:
    is_running: bool
    is_frontmost: bool
    process_identifier: int | None


class ApplicationBackend(Protocol):
    def status(self, bundle_identifier: str) -> ChessApplicationStatus: ...

    def activate(self, bundle_identifier: str) -> None: ...


class _PyObjCApplicationBackend:
    def __init__(self) -> None:
        from ._native import load_framework

        self._appkit = load_framework("AppKit")

    def status(self, bundle_identifier: str) -> ChessApplicationStatus:
        application = self._running_application(bundle_identifier)
        if application is None:
            return ChessApplicationStatus(False, False, None)
        return ChessApplicationStatus(
            True,
            bool(application.isActive()),
            _positive_process_identifier(application),
        )

    def activate(self, bundle_identifier: str) -> None:
        if bundle_identifier != CHESS_BUNDLE_IDENTIFIER:
            raise ValueError("only the exact Apple Chess bundle may be activated")

        application = self._running_application(bundle_identifier)
        if application is None:
            application = self._launch_exact_bundle(bundle_identifier)
        _positive_process_identifier(application)
        application.activateWithOptions_(
            self._appkit.NSApplicationActivateIgnoringOtherApps
        )

    def _launch_exact_bundle(self, bundle_identifier: str) -> Any:
        workspace = self._appkit.NSWorkspace.sharedWorkspace()
        application_url = workspace.URLForApplicationWithBundleIdentifier_(
            bundle_identifier
        )
        if application_url is None:
            raise ChessApplicationUnavailableError("Chess.app is not installed.")
        result = workspace.launchApplicationAtURL_options_configuration_error_(
            application_url,
            self._appkit.NSWorkspaceLaunchDefault,
            {},
            None,
        )
        if not isinstance(result, tuple) or len(result) != 2:
            raise ChessApplicationUnavailableError(
                "Chess.app returned an invalid launch result."
            )
        application, error = result
        if application is None:
            category = type(error).__name__ if error is not None else "unknown"
            raise ChessApplicationUnavailableError(
                f"Chess.app could not be launched ({category})."
            )
        return application

    def _running_application(self, bundle_identifier: str) -> Any | None:
        workspace = self._appkit.NSWorkspace.sharedWorkspace()
        matches = tuple(
            application
            for application in workspace.runningApplications()
            if application.bundleIdentifier() == bundle_identifier
            and not application.isTerminated()
        )
        if len(matches) > 1:
            raise ChessApplicationAmbiguousError(
                "Multiple running com.apple.Chess processes were found."
            )
        return matches[0] if matches else None


class ChessApplicationController:
    """Activates only ``com.apple.Chess`` and verifies the resulting PID/frontmost state."""

    def __init__(
        self,
        backend: ApplicationBackend | None = None,
        *,
        poll_interval: float = 0.025,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._backend = backend
        self._poll_interval = poll_interval
        self._sleep = sleep

    @property
    def backend(self) -> ApplicationBackend:
        if self._backend is None:
            self._backend = _PyObjCApplicationBackend()
        return self._backend

    async def status(self) -> ChessApplicationStatus:
        status = await run_on_main(lambda: self.backend.status(CHESS_BUNDLE_IDENTIFIER))
        if status.process_identifier is not None:
            _positive_process_identifier(status.process_identifier)
        return status

    async def activate(self, timeout: float = 3.0) -> ChessApplicationStatus:
        if timeout <= 0:
            raise ValueError("activation timeout must be positive")
        await run_on_main(lambda: self.backend.activate(CHESS_BUNDLE_IDENTIFIER))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            current = await self.status()
            if current.is_running and current.is_frontmost:
                if current.process_identifier is None:
                    raise ChessApplicationUnavailableError(
                        "Chess.app did not provide a valid process identifier."
                    )
                _positive_process_identifier(current.process_identifier)
                return current
            if loop.time() >= deadline:
                if not current.is_running:
                    raise ChessApplicationUnavailableError(
                        "Chess.app could not be found or launched."
                    )
                raise ChessActivationTimedOutError(
                    "Chess.app did not become active before the safety timeout."
                )
            await self._sleep(self._poll_interval)


def _positive_process_identifier(application_or_pid: Any) -> int:
    value = (
        application_or_pid.processIdentifier()
        if hasattr(application_or_pid, "processIdentifier")
        else application_or_pid
    )
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ChessApplicationUnavailableError(
            "Chess.app did not provide a valid process identifier."
        )
    return value
