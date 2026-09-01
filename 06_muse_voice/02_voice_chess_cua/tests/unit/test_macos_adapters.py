# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from voice_chess_cua.domain.geometry import Point, Rect
from voice_chess_cua.macos import appkit_host, application, permissions
from voice_chess_cua.macos._asyncio import call_soon_threadsafe_if_open
from voice_chess_cua.macos.appkit_host import AppKitHost
from voice_chess_cua.macos.application import (
    CHESS_BUNDLE_IDENTIFIER,
    ChessActivationTimedOutError,
    ChessApplicationAmbiguousError,
    ChessApplicationController,
    ChessApplicationStatus,
    ChessApplicationUnavailableError,
    _PyObjCApplicationBackend,
)
from voice_chess_cua.macos.capture import (
    WindowCaptureTimedOutError,
    WindowScreenshotProvider,
    WindowUnavailableError,
    _native_window_matches_candidate,
    _ScreenCaptureKitCaptureBackend,
)
from voice_chess_cua.macos.chess_accessibility import (
    _ApplicationServicesChessAccessibilityBackend,
)
from voice_chess_cua.macos.mouse import (
    CGEventPoster,
    EventCreationFailedError,
    EventPairPartiallyPostedError,
    EventSourceUnavailableError,
    EventTargetChangedError,
    _QuartzEventBackend,
)
from voice_chess_cua.macos.permissions import (
    MissingPermissionsError,
    PermissionController,
    PermissionGrant,
    _PyObjCPermissionBackend,
)
from voice_chess_cua.macos.windows import (
    AmbiguousChessWindowError,
    ChessWindowLocator,
    NoVisibleChessWindowError,
    ScreenCaptureKitError,
    ShareableContentTimedOutError,
    WindowCandidate,
    _native_error_code,
    _ScreenCaptureKitWindowBackend,
)


class NativeRunningApplication:
    def __init__(
        self,
        *,
        bundle_identifier: str = CHESS_BUNDLE_IDENTIFIER,
        process_identifier: int = 42,
        active: bool = False,
        terminated: bool = False,
    ) -> None:
        self.bundle_identifier = bundle_identifier
        self.process_identifier = process_identifier
        self.active = active
        self.terminated = terminated
        self.activation_options: list[int] = []

    def bundleIdentifier(self) -> str:
        return self.bundle_identifier

    def processIdentifier(self) -> int:
        return self.process_identifier

    def isActive(self) -> bool:
        return self.active

    def isTerminated(self) -> bool:
        return self.terminated

    def activateWithOptions_(self, options: int) -> None:
        self.activation_options.append(options)


_DEFAULT_NATIVE_VALUE = object()


class NativeWorkspace:
    def __init__(
        self,
        *,
        running: tuple[object, ...] = (),
        application_url: object | None = _DEFAULT_NATIVE_VALUE,
        launch_result: tuple[object | None, object | None] | None = None,
    ) -> None:
        self.running = running
        self.application_url = application_url
        self.launch_result = launch_result or (NativeRunningApplication(), None)
        self.launches: list[
            tuple[object, int, dict[object, object], object | None]
        ] = []

    def runningApplications(self) -> tuple[object, ...]:
        return self.running

    def URLForApplicationWithBundleIdentifier_(
        self, bundle_identifier: str
    ) -> object | None:
        assert bundle_identifier == CHESS_BUNDLE_IDENTIFIER
        return self.application_url

    def launchApplicationAtURL_options_configuration_error_(
        self,
        url: object,
        options: int,
        configuration: dict[object, object],
        error: object | None,
    ) -> tuple[object | None, object | None]:
        self.launches.append((url, options, configuration, error))
        return self.launch_result


class NativeAppKit:
    NSApplicationActivateIgnoringOtherApps = 2
    NSWorkspaceLaunchDefault = 65_536

    def __init__(self, workspace: NativeWorkspace) -> None:
        self._workspace = workspace
        self.NSWorkspace = SimpleNamespace(sharedWorkspace=lambda: workspace)


def native_backend(workspace: NativeWorkspace) -> _PyObjCApplicationBackend:
    backend = object.__new__(_PyObjCApplicationBackend)
    backend._appkit = NativeAppKit(workspace)
    return backend


def test_native_application_backend_launches_exact_bundle_and_activates() -> None:
    launched = NativeRunningApplication()
    application_url = object()
    workspace = NativeWorkspace(
        application_url=application_url,
        launch_result=(launched, None),
    )

    native_backend(workspace).activate(CHESS_BUNDLE_IDENTIFIER)

    assert workspace.launches == [(application_url, 65_536, {}, None)]
    assert launched.activation_options == [2]


def test_native_application_backend_reuses_only_one_live_exact_bundle() -> None:
    exact = NativeRunningApplication(process_identifier=17, active=True)
    workspace = NativeWorkspace(
        running=(
            NativeRunningApplication(bundle_identifier="com.example.Chess"),
            NativeRunningApplication(terminated=True),
            exact,
        )
    )
    backend = native_backend(workspace)

    backend.activate(CHESS_BUNDLE_IDENTIFIER)

    assert workspace.launches == []
    assert exact.activation_options == [2]
    assert backend.status(CHESS_BUNDLE_IDENTIFIER) == ChessApplicationStatus(
        True, True, 17
    )


def test_native_application_backend_rejects_ambiguous_exact_processes() -> None:
    workspace = NativeWorkspace(
        running=(
            NativeRunningApplication(),
            NativeRunningApplication(process_identifier=43),
        )
    )
    backend = native_backend(workspace)

    with pytest.raises(ChessApplicationAmbiguousError, match="Multiple running"):
        backend.activate(CHESS_BUNDLE_IDENTIFIER)

    assert workspace.launches == []


@pytest.mark.parametrize("process_identifier", (0, -1, True))
def test_native_application_backend_rejects_invalid_process_identifiers(
    process_identifier: int,
) -> None:
    running = NativeRunningApplication(process_identifier=process_identifier)
    backend = native_backend(NativeWorkspace(running=(running,)))

    with pytest.raises(ChessApplicationUnavailableError, match="process identifier"):
        backend.status(CHESS_BUNDLE_IDENTIFIER)
    with pytest.raises(ChessApplicationUnavailableError, match="process identifier"):
        backend.activate(CHESS_BUNDLE_IDENTIFIER)

    assert running.activation_options == []


def test_native_application_backend_rejects_invalid_launched_process_identifier() -> (
    None
):
    launched = NativeRunningApplication(process_identifier=0)
    workspace = NativeWorkspace(launch_result=(launched, None))

    with pytest.raises(ChessApplicationUnavailableError, match="process identifier"):
        native_backend(workspace).activate(CHESS_BUNDLE_IDENTIFIER)

    assert len(workspace.launches) == 1
    assert launched.activation_options == []


def test_native_application_backend_reports_missing_or_failed_chess_launch() -> None:
    with pytest.raises(ChessApplicationUnavailableError, match="not installed"):
        native_backend(NativeWorkspace(application_url=None)).activate(
            CHESS_BUNDLE_IDENTIFIER
        )

    with pytest.raises(ChessApplicationUnavailableError, match="could not be launched"):
        native_backend(
            NativeWorkspace(launch_result=(None, RuntimeError("launch failed")))
        ).activate(CHESS_BUNDLE_IDENTIFIER)


class ApplicationBackend:
    def __init__(self, statuses: list[ChessApplicationStatus]) -> None:
        self.statuses = statuses
        self.activations: list[str] = []

    def status(self, bundle_identifier: str) -> ChessApplicationStatus:
        assert bundle_identifier == CHESS_BUNDLE_IDENTIFIER
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def activate(self, bundle_identifier: str) -> None:
        self.activations.append(bundle_identifier)


@pytest.mark.asyncio
async def test_application_activates_only_exact_chess_and_waits_for_frontmost(
    monkeypatch,
) -> None:
    backend = ApplicationBackend(
        [
            ChessApplicationStatus(True, False, 42),
            ChessApplicationStatus(True, True, 42),
        ]
    )

    async def immediate(work):
        return work()

    monkeypatch.setattr(application, "run_on_main", immediate)
    controller = ChessApplicationController(backend, sleep=lambda _: asyncio.sleep(0))

    status = await controller.activate(timeout=1)

    assert backend.activations == ["com.apple.Chess"]
    assert status == ChessApplicationStatus(True, True, 42)


@pytest.mark.asyncio
async def test_application_activation_times_out_fail_closed(monkeypatch) -> None:
    backend = ApplicationBackend([ChessApplicationStatus(True, False, 42)])

    async def immediate(work):
        return work()

    monkeypatch.setattr(application, "run_on_main", immediate)
    controller = ChessApplicationController(backend)

    with pytest.raises(ChessActivationTimedOutError):
        await controller.activate(timeout=1e-9)


class NeverCompletingShareableContent:
    @staticmethod
    def getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
        exclude_desktop: bool,
        on_screen_only: bool,
        completed: object,
    ) -> None:
        assert exclude_desktop is False
        assert on_screen_only is True
        assert callable(completed)


class NeverCompletingScreenCaptureKit:
    SCShareableContent = NeverCompletingShareableContent


class RetainedShareableContent:
    completed: object | None = None

    @classmethod
    def getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
        cls,
        exclude_desktop: bool,
        on_screen_only: bool,
        completed: object,
    ) -> None:
        assert exclude_desktop is False
        assert on_screen_only is True
        assert callable(completed)
        cls.completed = completed


class RetainedScreenCaptureKit:
    SCShareableContent = RetainedShareableContent


class WindowBackend:
    def __init__(self, candidates: tuple[WindowCandidate, ...]) -> None:
        self.candidates = candidates

    async def windows(self) -> tuple[WindowCandidate, ...]:
        return self.candidates


def candidate(
    window_id: int,
    *,
    bundle: str = CHESS_BUNDLE_IDENTIFIER,
    process_id: int = 42,
    on_screen: bool = True,
) -> WindowCandidate:
    return WindowCandidate(
        window_id=window_id,
        frame=Rect(100, 200, 800, 600),
        title="Game",
        application_name="Chess",
        process_id=process_id,
        is_frontmost=True,
        display_ids=(1,),
        bundle_identifier=bundle,
        is_on_screen=on_screen,
    )


@pytest.mark.asyncio
async def test_native_window_discovery_times_out_when_callback_never_fires() -> None:
    backend = object.__new__(_ScreenCaptureKitWindowBackend)
    backend._screen_capture_kit = NeverCompletingScreenCaptureKit()
    backend._shareable_content_timeout = 0.001

    with pytest.raises(ShareableContentTimedOutError, match="timed out"):
        await backend._shareable_content()


def test_native_window_discovery_drops_callback_after_loop_closes() -> None:
    RetainedShareableContent.completed = None
    backend = object.__new__(_ScreenCaptureKitWindowBackend)
    backend._screen_capture_kit = RetainedScreenCaptureKit()
    backend._shareable_content_timeout = 0.001
    loop = asyncio.new_event_loop()

    try:
        with pytest.raises(ShareableContentTimedOutError, match="timed out"):
            loop.run_until_complete(backend._shareable_content())
        completed = RetainedShareableContent.completed
        assert callable(completed)
    finally:
        loop.close()

    completed(object(), None)
    completed(None, RuntimeError("late native error"))


class ClosingLoopRace:
    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, callback: object) -> None:
        del callback
        raise RuntimeError("Event loop is closed")


def test_native_callback_dispatch_drops_loop_close_race() -> None:
    assert not call_soon_threadsafe_if_open(ClosingLoopRace(), lambda: None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_native_window_discovery_preserves_only_numeric_error_code() -> None:
    class FailingShareableContent:
        @staticmethod
        def getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            exclude_desktop: bool,
            on_screen_only: bool,
            completed: object,
        ) -> None:
            del exclude_desktop, on_screen_only
            assert callable(completed)
            completed(None, SimpleNamespace(code=-3801, description="private detail"))

    backend = object.__new__(_ScreenCaptureKitWindowBackend)
    backend._screen_capture_kit = SimpleNamespace(
        SCShareableContent=FailingShareableContent
    )
    backend._shareable_content_timeout = 1.0

    with pytest.raises(ScreenCaptureKitError) as raised:
        await backend._shareable_content()

    assert raised.value.code == -3801
    assert "private detail" not in str(raised.value)

    callable_code = SimpleNamespace(code=lambda: -3801)
    assert _native_error_code(callable_code) == -3801


@pytest.mark.asyncio
async def test_window_locator_filters_exact_bundle_pid_and_visibility() -> None:
    backend = WindowBackend(
        (
            candidate(1, bundle="com.example.Chess"),
            candidate(2, process_id=99),
            candidate(3, on_screen=False),
            candidate(4),
        )
    )

    selected = await ChessWindowLocator(backend).locate(expected_process_id=42)

    assert selected.window_id == 4
    assert selected.process_id == 42
    assert selected.bundle_identifier == "com.apple.Chess"
    assert selected.display_ids == (1,)


@pytest.mark.asyncio
async def test_window_locator_rejects_zero_or_multiple_eligible_windows() -> None:
    with pytest.raises(NoVisibleChessWindowError):
        await ChessWindowLocator(WindowBackend(())).locate()

    with pytest.raises(AmbiguousChessWindowError) as raised:
        await ChessWindowLocator(WindowBackend((candidate(7), candidate(8)))).locate()

    assert raised.value.window_ids == (7, 8)


@pytest.mark.asyncio
@pytest.mark.parametrize("process_identifier", (0, -1, True))
async def test_window_locator_rejects_invalid_expected_process_identifier(
    process_identifier: int,
) -> None:
    backend = WindowBackend((candidate(7),))

    with pytest.raises(ValueError, match="positive integer"):
        await ChessWindowLocator(backend).locate(expected_process_id=process_identifier)


@pytest.mark.asyncio
@pytest.mark.parametrize("process_identifier", (0, -1, True))
async def test_window_locator_ignores_candidates_with_invalid_process_identifier(
    process_identifier: int,
) -> None:
    with pytest.raises(NoVisibleChessWindowError):
        await ChessWindowLocator(
            WindowBackend((candidate(7, process_id=process_identifier),))
        ).locate()


class NativeFilter:
    def pointPixelScale(self) -> float:
        return 1.0


class NativeFilterFactory:
    @staticmethod
    def alloc() -> NativeFilterFactory:
        return NativeFilterFactory()

    def initWithDesktopIndependentWindow_(self, window: object) -> NativeFilter:
        del window
        return NativeFilter()


class NativeConfiguration:
    def setWidth_(self, width: int) -> None:
        del width

    def setHeight_(self, height: int) -> None:
        del height

    def setShowsCursor_(self, shows_cursor: bool) -> None:
        del shows_cursor

    def setCapturesAudio_(self, captures_audio: bool) -> None:
        del captures_audio


class NativeConfigurationFactory:
    @staticmethod
    def alloc() -> NativeConfigurationFactory:
        return NativeConfigurationFactory()

    def init(self) -> NativeConfiguration:
        return NativeConfiguration()


class NeverCompletingScreenshotManager:
    @staticmethod
    def captureImageWithFilter_configuration_completionHandler_(
        filter_: object,
        configuration: object,
        completed: object,
    ) -> None:
        assert filter_ is not None
        assert configuration is not None
        assert callable(completed)


class NeverCompletingCaptureKit:
    SCContentFilter = NativeFilterFactory
    SCStreamConfiguration = NativeConfigurationFactory
    SCScreenshotManager = NeverCompletingScreenshotManager


class RetainedScreenshotManager:
    completed: object | None = None

    @classmethod
    def captureImageWithFilter_configuration_completionHandler_(
        cls,
        filter_: object,
        configuration: object,
        completed: object,
    ) -> None:
        assert filter_ is not None
        assert configuration is not None
        assert callable(completed)
        cls.completed = completed


class RetainedCaptureKit:
    SCContentFilter = NativeFilterFactory
    SCStreamConfiguration = NativeConfigurationFactory
    SCScreenshotManager = RetainedScreenshotManager


class NativeWindowForCapture:
    def windowID(self) -> int:
        return 9

    def isOnScreen(self) -> bool:
        return True

    def owningApplication(self) -> object:
        return SimpleNamespace(
            bundleIdentifier=lambda: CHESS_BUNDLE_IDENTIFIER,
            processID=lambda: 42,
        )


class ShareableContentForCapture:
    def windows(self) -> tuple[NativeWindowForCapture, ...]:
        return (NativeWindowForCapture(),)


class CaptureBackend:
    def __init__(self, image: object) -> None:
        self.image = image
        self.captured: list[int] = []

    async def capture(self, selected: WindowCandidate) -> object:
        self.captured.append(selected.window_id)
        return self.image


@pytest.mark.asyncio
async def test_native_capture_times_out_when_callback_never_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = object.__new__(_ScreenCaptureKitCaptureBackend)
    backend._screen_capture_kit = NeverCompletingCaptureKit()
    backend._capture_timeout = 0.001

    async def shareable_content(self: object) -> ShareableContentForCapture:
        del self
        return ShareableContentForCapture()

    monkeypatch.setattr(
        _ScreenCaptureKitWindowBackend,
        "_shareable_content",
        shareable_content,
    )

    with pytest.raises(WindowCaptureTimedOutError, match="timed out"):
        await backend.capture(candidate(9))


def test_native_capture_drops_callback_after_loop_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RetainedScreenshotManager.completed = None
    backend = object.__new__(_ScreenCaptureKitCaptureBackend)
    backend._screen_capture_kit = RetainedCaptureKit()
    backend._capture_timeout = 0.001

    async def shareable_content(self: object) -> ShareableContentForCapture:
        del self
        return ShareableContentForCapture()

    monkeypatch.setattr(
        _ScreenCaptureKitWindowBackend,
        "_shareable_content",
        shareable_content,
    )
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(WindowCaptureTimedOutError, match="timed out"):
            loop.run_until_complete(backend.capture(candidate(9)))
        completed = RetainedScreenshotManager.completed
        assert callable(completed)
    finally:
        loop.close()

    completed(object(), None)
    completed(None, RuntimeError("late native error"))


@pytest.mark.asyncio
async def test_capture_preserves_window_metadata_and_pixel_scale() -> None:
    native_image = SimpleNamespace(width=1600, height=900)
    capture_backend = CaptureBackend(native_image)
    screenshot = await WindowScreenshotProvider(
        WindowBackend((candidate(9),)),
        capture_backend,
    ).capture(9)

    assert screenshot.image is native_image
    assert screenshot.image_size.width == 1600
    assert screenshot.image_size.height == 900
    assert screenshot.point_pixel_scale_x == 2
    assert screenshot.point_pixel_scale_y == 1.5
    assert screenshot.window.window_id == 9
    assert capture_backend.captured == [9]


def test_native_capture_revalidation_checks_bundle_pid_and_visibility() -> None:
    class NativeApplication:
        def __init__(self, bundle: str, process_id: int) -> None:
            self.bundle = bundle
            self.process_id = process_id

        def bundleIdentifier(self) -> str:
            return self.bundle

        def processID(self) -> int:
            return self.process_id

    class NativeWindow:
        def __init__(self, bundle: str, process_id: int, on_screen: bool) -> None:
            self.application = NativeApplication(bundle, process_id)
            self.on_screen = on_screen

        def windowID(self) -> int:
            return 9

        def owningApplication(self) -> NativeApplication:
            return self.application

        def isOnScreen(self) -> bool:
            return self.on_screen

    selected = candidate(9)
    assert _native_window_matches_candidate(
        NativeWindow(CHESS_BUNDLE_IDENTIFIER, 42, True), selected
    )
    assert not _native_window_matches_candidate(
        NativeWindow("com.example.Other", 42, True), selected
    )
    assert not _native_window_matches_candidate(
        NativeWindow(CHESS_BUNDLE_IDENTIFIER, 99, True), selected
    )
    assert not _native_window_matches_candidate(
        NativeWindow(CHESS_BUNDLE_IDENTIFIER, 42, False), selected
    )


@pytest.mark.asyncio
async def test_capture_rejects_stale_or_non_chess_window() -> None:
    provider = WindowScreenshotProvider(
        WindowBackend((candidate(9, bundle="com.example.Other"),)),
        CaptureBackend(SimpleNamespace(width=100, height=100)),
    )

    with pytest.raises(WindowUnavailableError):
        await provider.capture(9)


def test_direct_permission_status_functions_load_only_the_required_framework(
    monkeypatch,
) -> None:
    loaded: list[str] = []
    application_services = SimpleNamespace(AXIsProcessTrusted=Mock(return_value=1))
    quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=Mock(return_value=0))
    frameworks = {
        "ApplicationServices": application_services,
        "Quartz": quartz,
    }

    def load_framework(name: str) -> object:
        loaded.append(name)
        return frameworks[name]

    monkeypatch.setattr(permissions, "_load_native_framework", load_framework)

    assert permissions.is_accessibility_trusted() is True
    assert permissions.has_screen_recording_access() is False
    assert loaded == ["ApplicationServices", "Quartz"]
    application_services.AXIsProcessTrusted.assert_called_once_with()
    quartz.CGPreflightScreenCaptureAccess.assert_called_once_with()


def _native_permission_backend(
    monkeypatch,
    *,
    accessibility_trusted: bool,
    screen_recording_allowed: bool,
) -> tuple[_PyObjCPermissionBackend, object, object]:
    av_foundation = SimpleNamespace()
    application_services = SimpleNamespace(
        AXIsProcessTrusted=Mock(return_value=accessibility_trusted),
        AXIsProcessTrustedWithOptions=Mock(return_value=True),
    )
    quartz = SimpleNamespace(
        CGPreflightScreenCaptureAccess=Mock(return_value=screen_recording_allowed),
        CGRequestScreenCaptureAccess=Mock(return_value=True),
    )
    frameworks = {
        "AVFoundation": av_foundation,
        "ApplicationServices": application_services,
        "Quartz": quartz,
    }
    monkeypatch.setattr(
        permissions,
        "_load_native_framework",
        lambda name: frameworks[name],
    )
    return _PyObjCPermissionBackend(), application_services, quartz


def test_native_permission_requests_use_exact_prompting_primitives(monkeypatch) -> None:
    backend, application_services, quartz = _native_permission_backend(
        monkeypatch,
        accessibility_trusted=False,
        screen_recording_allowed=False,
    )

    assert backend.accessibility_status() is False
    assert backend.screen_recording_status() is False
    assert backend.request_accessibility() is True
    assert backend.request_screen_recording() is True

    application_services.AXIsProcessTrustedWithOptions.assert_called_once_with(
        {"AXTrustedCheckOptionPrompt": True}
    )
    quartz.CGRequestScreenCaptureAccess.assert_called_once_with()


def test_native_permission_requests_do_not_prompt_when_already_granted(
    monkeypatch,
) -> None:
    backend, application_services, quartz = _native_permission_backend(
        monkeypatch,
        accessibility_trusted=True,
        screen_recording_allowed=True,
    )

    assert backend.request_accessibility() is True
    assert backend.request_screen_recording() is True

    application_services.AXIsProcessTrustedWithOptions.assert_not_called()
    quartz.CGRequestScreenCaptureAccess.assert_not_called()


class PermissionBackend:
    def __init__(self) -> None:
        self.microphone = PermissionGrant.UNKNOWN
        self.accessibility = False
        self.screen = True
        self.requests: list[str] = []

    def microphone_status(self) -> PermissionGrant:
        return self.microphone

    async def request_microphone(self) -> bool:
        self.requests.append("microphone")
        self.microphone = PermissionGrant.GRANTED
        return True

    def accessibility_status(self) -> bool:
        return self.accessibility

    def request_accessibility(self) -> bool:
        self.requests.append("accessibility")
        self.accessibility = True
        return True

    def screen_recording_status(self) -> bool:
        return self.screen

    def request_screen_recording(self) -> bool:
        self.requests.append("screen")
        self.screen = True
        return True


@pytest.mark.asyncio
async def test_permission_snapshot_and_verify_never_prompt() -> None:
    backend = PermissionBackend()
    controller = PermissionController(backend)

    snapshot = controller.snapshot()
    with pytest.raises(MissingPermissionsError) as raised:
        await controller.verify_required()

    assert snapshot.microphone is PermissionGrant.UNKNOWN
    assert snapshot.accessibility is PermissionGrant.DENIED
    assert snapshot.screen_recording is PermissionGrant.GRANTED
    assert raised.value.snapshot == snapshot
    assert backend.requests == []


@pytest.mark.asyncio
async def test_selective_permission_verification_ignores_unneeded_grants() -> None:
    backend = PermissionBackend()
    backend.accessibility = True
    controller = PermissionController(backend)

    await controller.verify_required(microphone=False)
    await controller.verify_required(microphone=False, accessibility=False)

    assert backend.requests == []


@pytest.mark.asyncio
async def test_request_missing_prompts_only_missing_permissions() -> None:
    backend = PermissionBackend()

    snapshot = await PermissionController(backend).request_missing()

    assert snapshot.all_granted
    assert backend.requests == ["microphone", "accessibility"]


def test_ax_element_collection_accepts_native_iterables() -> None:
    class NativeArray:
        def __iter__(self):
            return iter(("first", "second"))

    assert _ApplicationServicesChessAccessibilityBackend._elements(NativeArray()) == (
        "first",
        "second",
    )
    assert _ApplicationServicesChessAccessibilityBackend._elements(None) == ()
    assert _ApplicationServicesChessAccessibilityBackend._elements("not-elements") == ()


def test_native_event_backend_creates_combined_session_source() -> None:
    source = object()
    quartz = SimpleNamespace(
        kCGEventSourceStateCombinedSessionState=7,
        CGEventSourceCreate=Mock(return_value=source),
    )
    backend = object.__new__(_QuartzEventBackend)
    backend._quartz = quartz

    assert backend.create_source() is source
    quartz.CGEventSourceCreate.assert_called_once_with(7)


class EventBackend:
    def __init__(self, events: tuple[object | None, object | None]) -> None:
        self.events = events
        self.posts: list[object] = []
        self.click_points: list[Point] = []
        self.frontmost_process_identifier = 42

    def create_source(self) -> object | None:
        return "source"

    def click_events(
        self, source: object, point: Point
    ) -> tuple[object | None, object | None]:
        assert source == "source"
        self.click_points.append(point)
        return self.events

    def target_is_frontmost(self, process_identifier: int) -> bool:
        return process_identifier == self.frontmost_process_identifier

    def post(self, event: object) -> None:
        self.posts.append(event)


@pytest.mark.asyncio
async def test_event_poster_fails_closed_when_event_source_is_unavailable() -> None:
    class SourceUnavailableBackend(EventBackend):
        def create_source(self) -> None:
            return None

    backend = SourceUnavailableBackend(("down", "up"))

    with pytest.raises(EventSourceUnavailableError):
        await CGEventPoster(backend).click(Point(12, 34), 42)

    assert backend.click_points == []
    assert backend.posts == []


@pytest.mark.asyncio
async def test_event_poster_posts_complete_pairs_in_order() -> None:
    backend = EventBackend(("down", "up"))
    poster = CGEventPoster(backend)

    await poster.click(Point(12, 34), 42)

    assert backend.click_points == [Point(12, 34)]
    assert backend.posts == ["down", "up"]


@pytest.mark.asyncio
async def test_event_poster_serializes_concurrent_event_pairs() -> None:
    class BlockingBackend(EventBackend):
        def __init__(self, event_loop: asyncio.AbstractEventLoop) -> None:
            super().__init__(("down", "up"))
            self.event_loop = event_loop
            self.first_posted = asyncio.Event()
            self.release = asyncio.Event()

        def post(self, event: object) -> None:
            self.posts.append(event)
            if len(self.posts) == 1:
                asyncio.run_coroutine_threadsafe(
                    self._release_later(), self.event_loop
                ).result()

        async def _release_later(self) -> None:
            self.first_posted.set()
            await self.release.wait()

    backend = BlockingBackend(asyncio.get_running_loop())
    poster = CGEventPoster(backend)
    first = asyncio.create_task(poster.click(Point(1, 2), 42))
    await backend.first_posted.wait()
    second = asyncio.create_task(poster.click(Point(3, 4), 42))
    await asyncio.sleep(0)
    assert backend.posts == ["down"]
    backend.release.set()
    await asyncio.gather(first, second)
    assert backend.click_points == [Point(1, 2), Point(3, 4)]
    assert backend.posts == ["down", "up", "down", "up"]


@pytest.mark.asyncio
async def test_event_poster_retries_release_after_partial_pair_failure() -> None:
    class ReleaseFailingBackend(EventBackend):
        def post(self, event: object) -> None:
            self.posts.append(event)
            if event == "up":
                raise OSError("release failed")

    backend = ReleaseFailingBackend(("down", "up"))

    with pytest.raises(EventPairPartiallyPostedError):
        await CGEventPoster(backend).click(Point(12, 34), 42)

    assert backend.posts == ["down", "up", "up"]


@pytest.mark.asyncio
async def test_event_poster_posts_nothing_when_exact_chess_pid_is_not_frontmost() -> (
    None
):
    backend = EventBackend(("down", "up"))
    backend.frontmost_process_identifier = 99

    with pytest.raises(EventTargetChangedError):
        await CGEventPoster(backend).click(Point(12, 34), 42)

    assert backend.posts == []


@pytest.mark.asyncio
async def test_event_poster_posts_nothing_when_either_event_is_missing() -> None:
    backend = EventBackend(("down", None))

    with pytest.raises(EventCreationFailedError):
        await CGEventPoster(backend).click(Point(12, 34), 42)

    assert backend.posts == []


@dataclass
class FakeApplication:
    ran: bool = False
    stopped: bool = False
    posted_events: list[tuple[object, bool]] = field(default_factory=list)

    def run(self) -> None:
        self.ran = True

    def stop_(self, sender: object | None) -> None:
        assert sender is None
        self.stopped = True

    def postEvent_atStart_(self, event: object, at_start: bool) -> None:
        self.posted_events.append((event, at_start))


@pytest.mark.asyncio
async def test_appkit_host_returns_exit_code_and_stops_injected_run_loop() -> None:
    fake = FakeApplication()
    host = AppKitHost(fake)

    async def immediate(work):
        return work()

    wake_event = object()
    fake_appkit = SimpleNamespace(
        NSEventTypeApplicationDefined=15,
        NSEvent=SimpleNamespace(
            otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_=lambda *args: (
                wake_event
            )
        ),
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(appkit_host, "run_on_main", immediate)
    monkeypatch.setattr(appkit_host, "load_framework", lambda name: fake_appkit)
    host._running = True
    try:
        await host.stop(143)
    finally:
        monkeypatch.undo()
    result = host.run()

    assert fake.stopped
    assert host.stop_requested
    assert fake.posted_events == [(wake_event, True)]
    assert not fake.ran
    assert result == 143


@pytest.mark.asyncio
async def test_appkit_host_stop_before_run_never_enters_native_loop() -> None:
    fake = FakeApplication()
    host = AppKitHost(fake)

    await host.stop(4)

    assert host.run() == 4
    assert host.stop_requested
    assert not fake.ran
    assert not fake.stopped
    assert fake.posted_events == []
