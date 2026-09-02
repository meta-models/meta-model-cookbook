# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Read-only permission status and explicitly prompting requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType
from typing import Protocol

from .native import call_soon_threadsafe_if_open


class PermissionGrant(StrEnum):
    UNKNOWN = "unknown"
    DENIED = "denied"
    GRANTED = "granted"


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    microphone: PermissionGrant
    accessibility: PermissionGrant
    screen_recording: PermissionGrant

    @property
    def all_granted(self) -> bool:
        return all(
            grant is PermissionGrant.GRANTED
            for grant in (self.microphone, self.accessibility, self.screen_recording)
        )


class MissingPermissionsError(RuntimeError):
    def __init__(self, snapshot: PermissionSnapshot) -> None:
        self.snapshot = snapshot
        missing = tuple(
            name
            for name, grant in (
                ("microphone", snapshot.microphone),
                ("accessibility", snapshot.accessibility),
                ("screen recording", snapshot.screen_recording),
            )
            if grant is not PermissionGrant.GRANTED
        )
        super().__init__("Required permissions are not granted: " + ", ".join(missing))


class PermissionBackend(Protocol):
    def microphone_status(self) -> PermissionGrant: ...

    async def request_microphone(self) -> bool: ...

    def accessibility_status(self) -> bool: ...

    def request_accessibility(self) -> bool: ...

    def screen_recording_status(self) -> bool: ...

    def request_screen_recording(self) -> bool: ...


def _load_native_framework(module_name: str) -> ModuleType:
    from .native import load_framework

    return load_framework(module_name)


def is_accessibility_trusted() -> bool:
    application_services = _load_native_framework("ApplicationServices")
    return bool(application_services.AXIsProcessTrusted())


def has_screen_recording_access() -> bool:
    quartz = _load_native_framework("Quartz")
    return bool(quartz.CGPreflightScreenCaptureAccess())


class _PyObjCPermissionBackend:
    def __init__(self) -> None:
        self._av_foundation = _load_native_framework("AVFoundation")
        self._application_services = _load_native_framework("ApplicationServices")
        self._quartz = _load_native_framework("Quartz")

    def microphone_status(self) -> PermissionGrant:
        status = self._av_foundation.AVCaptureDevice.authorizationStatusForMediaType_(
            self._av_foundation.AVMediaTypeAudio
        )
        if status == self._av_foundation.AVAuthorizationStatusAuthorized:
            return PermissionGrant.GRANTED
        if status == self._av_foundation.AVAuthorizationStatusNotDetermined:
            return PermissionGrant.UNKNOWN
        return PermissionGrant.DENIED

    async def request_microphone(self) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def completed(granted: bool) -> None:
            def resolve() -> None:
                if not future.done():
                    future.set_result(bool(granted))

            call_soon_threadsafe_if_open(loop, resolve)

        self._av_foundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            self._av_foundation.AVMediaTypeAudio,
            completed,
        )
        return await future

    def accessibility_status(self) -> bool:
        return bool(self._application_services.AXIsProcessTrusted())

    def request_accessibility(self) -> bool:
        if self._application_services.AXIsProcessTrusted():
            return True
        return bool(
            self._application_services.AXIsProcessTrustedWithOptions(
                {"AXTrustedCheckOptionPrompt": True}
            )
        )

    def screen_recording_status(self) -> bool:
        return bool(self._quartz.CGPreflightScreenCaptureAccess())

    def request_screen_recording(self) -> bool:
        if self._quartz.CGPreflightScreenCaptureAccess():
            return True
        return bool(self._quartz.CGRequestScreenCaptureAccess())


class PermissionController:
    def __init__(self, backend: PermissionBackend | None = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> PermissionBackend:
        if self._backend is None:
            self._backend = _PyObjCPermissionBackend()
        return self._backend

    def snapshot(self) -> PermissionSnapshot:
        return PermissionSnapshot(
            microphone=self.backend.microphone_status(),
            accessibility=_grant(self.backend.accessibility_status()),
            screen_recording=_grant(self.backend.screen_recording_status()),
        )

    async def verify_required(
        self,
        *,
        microphone: bool = True,
        accessibility: bool = True,
        screen_recording: bool = True,
    ) -> None:
        snapshot = self.snapshot()
        required = (
            (microphone, snapshot.microphone),
            (accessibility, snapshot.accessibility),
            (screen_recording, snapshot.screen_recording),
        )
        if any(
            needed and grant is not PermissionGrant.GRANTED
            for needed, grant in required
        ):
            raise MissingPermissionsError(snapshot)

    async def request_missing(self) -> PermissionSnapshot:
        current = self.snapshot()
        if current.microphone is not PermissionGrant.GRANTED:
            await self.backend.request_microphone()
        if current.accessibility is not PermissionGrant.GRANTED:
            self.backend.request_accessibility()
        if current.screen_recording is not PermissionGrant.GRANTED:
            self.backend.request_screen_recording()
        return self.snapshot()

    async def request_microphone(self) -> PermissionSnapshot:
        await self.backend.request_microphone()
        return self.snapshot()

    def request_accessibility(self) -> PermissionSnapshot:
        self.backend.request_accessibility()
        return self.snapshot()

    def request_screen_recording(self) -> PermissionSnapshot:
        self.backend.request_screen_recording()
        return self.snapshot()


def _grant(value: bool) -> PermissionGrant:
    return PermissionGrant.GRANTED if value else PermissionGrant.DENIED
