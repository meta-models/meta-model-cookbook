# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Default CLI services and live Voice CUA object composition."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from voice_chess_cua.cli import CLIExitCode, CLIInvocation, CommandName
from voice_chess_cua.domain.chess import BoardOrientation, ChessSquare
from voice_chess_cua.domain.geometry import (
    BoardDetection,
    BoardGeometry,
    Point,
    Quad,
    Rect,
)
from voice_chess_cua.events import (
    RuntimeEvent,
    RuntimeEventSeverity,
    RuntimeStage,
    TerminalEventSink,
)
from voice_chess_cua.macos.appkit_host import AppKitHost
from voice_chess_cua.macos.application import ChessApplicationController
from voice_chess_cua.macos.audio import AudioCaptureService
from voice_chess_cua.macos.chess_accessibility import (
    ChessBoardAccessibilityProbe,
    ChessMovePostcondition,
)
from voice_chess_cua.macos.chess_state import (
    ChessAccessibilitySnapshotProbe,
    ChessStateObserver,
)
from voice_chess_cua.macos.mouse import CGEventPoster
from voice_chess_cua.macos.overlay import BoardOverlay
from voice_chess_cua.macos.permissions import PermissionController
from voice_chess_cua.macos.windows import (
    AmbiguousChessWindowError,
    ChessWindowLocator,
    NoVisibleChessWindowError,
    ScreenCaptureKitError,
    ShareableContentTimedOutError,
)
from voice_chess_cua.runtime.app import RuntimeDependencies, VoiceCUARuntime
from voice_chess_cua.runtime.ports import RuntimeCredentials, TrackingFailureReason
from voice_chess_cua.settings import (
    MODEL_API_KEY_ENVIRONMENT,
    STANDARD_SAFETY_POLICY,
    AppSettings,
)
from voice_chess_cua.vision.calibration import (
    AppleChessBoardCalibration,
    CalibrationError,
    UnsupportedAspectRatioError,
)
from voice_chess_cua.vision.tracking import (
    BoardDetectionError,
    BoardTrackingPolicy,
    BoardTrackingService,
)
from voice_chess_cua.voice.asr_client import VoiceASRClient
from voice_chess_cua.voice.asr_protocol import Mode
from voice_chess_cua.voice.asr_supervisor import ASRSupervisor
from voice_chess_cua.voice.chess_vocabulary import CHESS_ASR_KEYWORDS

from .process import AppKitRuntimeProcess


class RuntimeProcess(Protocol):
    def run(self) -> int: ...


class FixedSettingsProvider:
    async def load_validated(self) -> AppSettings:
        return AppSettings().validated()


class EnvironmentRuntimeCredentialProvider:
    async def load_runtime_credentials(self) -> RuntimeCredentials:
        value = os.environ.get(MODEL_API_KEY_ENVIRONMENT, "").strip()
        if not value:
            raise ValueError("MODEL_API_KEY is required.")
        return RuntimeCredentials(value)


DetectionClock = Callable[[], datetime]


class FixedCalibrationDetector:
    """Derive the board quad from the window calibration, validated by AX landmarks."""

    def __init__(
        self,
        application: ChessApplicationController,
        window_locator: ChessWindowLocator,
        accessibility_probe: ChessBoardAccessibilityProbe | None = None,
        calibration: AppleChessBoardCalibration = AppleChessBoardCalibration.current,
        *,
        clock: DetectionClock | None = None,
    ) -> None:
        self._application = application
        self._window_locator = window_locator
        self._accessibility_probe = (
            accessibility_probe or ChessBoardAccessibilityProbe()
        )
        self._calibration = calibration
        self._clock = clock or (lambda: datetime.now(UTC))

    async def detect(self) -> BoardDetection:
        bound_process_identifier = self._application.bound_process_identifier
        if not _is_positive_identifier(bound_process_identifier):
            raise BoardDetectionError(TrackingFailureReason.WINDOW_UNAVAILABLE)
        application = await self._application.status()
        if (
            not application.is_running
            or application.process_identifier != bound_process_identifier
        ):
            raise BoardDetectionError(TrackingFailureReason.WINDOW_UNAVAILABLE)
        try:
            window = await self._window_locator.locate(bound_process_identifier)
        except ScreenCaptureKitError as error:
            raise BoardDetectionError(_screen_capture_reason(error)) from error
        except ShareableContentTimedOutError as error:
            raise BoardDetectionError(
                TrackingFailureReason.WINDOW_DISCOVERY_TIMEOUT
            ) from error
        except AmbiguousChessWindowError as error:
            raise BoardDetectionError(TrackingFailureReason.WINDOW_AMBIGUOUS) from error
        except NoVisibleChessWindowError as error:
            raise BoardDetectionError(
                TrackingFailureReason.WINDOW_UNAVAILABLE
            ) from error
        if "Auto-Match Player" in (window.title or ""):
            raise BoardDetectionError(TrackingFailureReason.LAYOUT_MISMATCH)
        if window.process_id != bound_process_identifier:
            raise BoardDetectionError(TrackingFailureReason.WINDOW_UNAVAILABLE)
        try:
            geometry = BoardGeometry(
                self._calibration.window_quad(window.frame),
                BoardOrientation.WHITE_BOTTOM,
            )
        except UnsupportedAspectRatioError as error:
            raise BoardDetectionError(
                TrackingFailureReason.UNSUPPORTED_ASPECT
            ) from error
        except CalibrationError as error:
            raise BoardDetectionError(TrackingFailureReason.DETECTION_FAILED) from error
        try:
            centers = _validated_landmarks(
                await self._accessibility_probe.square_centers(
                    bound_process_identifier
                ),
                window.frame,
            )
        except BoardDetectionError:
            raise
        except Exception as error:
            raise BoardDetectionError(TrackingFailureReason.LAYOUT_MISMATCH) from error
        if not _landmarks_are_white_bottom(centers):
            raise BoardDetectionError(TrackingFailureReason.UNSUPPORTED_ORIENTATION)
        if not _landmark_distances_match(centers, geometry):
            raise BoardDetectionError(TrackingFailureReason.LAYOUT_MISMATCH)
        return BoardDetection(
            geometry=geometry,
            confidence=0.99,
            captured_at=self._clock(),
            source_window_id=window.window_id,
        )


def _is_positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


LANDMARK_NAMES = ("a1", "h1", "a8", "h8")
_LANDMARK_PAIRS = (("a1", "h1"), ("a8", "h8"), ("a1", "a8"), ("h1", "h8"))
# Apple Chess reports landmark positions with the vertical axis inverted, so the
# calibrated quad can only be compared against the distances between landmarks.
# Both window sizes the demo has been measured on agree to within 4%.
_MAXIMUM_LANDMARK_DISTANCE_ERROR = 0.05


def _validated_landmarks(
    centers: Mapping[str, Point],
    window_frame: Rect,
) -> dict[str, Point]:
    normalized = {
        square: center
        for square, center in centers.items()
        if isinstance(square, str) and square in LANDMARK_NAMES
    }
    if set(normalized) != set(LANDMARK_NAMES) or len(normalized) != len(centers):
        raise ValueError("Accessibility board landmarks are incomplete")
    if not all(
        isinstance(center, Point) and center.is_finite for center in normalized.values()
    ):
        raise ValueError("Accessibility board landmarks are malformed")
    if not all(window_frame.contains(center) for center in normalized.values()):
        raise ValueError("Accessibility board landmarks fall outside the window")
    return normalized


def _landmarks_are_white_bottom(centers: Mapping[str, Point]) -> bool:
    """Decide orientation from the landmark spread instead of their ranks.

    The near rank of a perspective board is always the wider one, and that
    holds whichever way Apple Chess reports the vertical axis.
    """

    rank_one_width = centers["h1"].x - centers["a1"].x
    rank_eight_width = centers["h8"].x - centers["a8"].x
    return 0 < rank_eight_width < rank_one_width


def _landmark_distances_match(
    centers: Mapping[str, Point],
    geometry: BoardGeometry,
) -> bool:
    expected = {
        square: geometry.center_of(ChessSquare.parse(square.upper()))
        for square in LANDMARK_NAMES
    }
    for start, end in _LANDMARK_PAIRS:
        calibrated = expected[start].distance_to(expected[end])
        measured = centers[start].distance_to(centers[end])
        if abs(measured - calibrated) / calibrated > _MAXIMUM_LANDMARK_DISTANCE_ERROR:
            return False
    return True


def _screen_capture_reason(error: ScreenCaptureKitError) -> TrackingFailureReason:
    if error.code == -3801:
        return TrackingFailureReason.SCREEN_CAPTURE_PERMISSION
    return TrackingFailureReason.DETECTION_FAILED


@dataclass(frozen=True, slots=True)
class LiveRuntimeComponents:
    runtime: VoiceCUARuntime
    application_host: AppKitHost


def build_live_runtime(*, dry_run: bool = False) -> LiveRuntimeComponents:
    """Construct native adapters lazily after the CLI selects the run command."""

    from voice_chess_cua.automation.move_executor import (
        ChessApplicationControllerPort,
        ChessMoveExecutor,
        ChessWindowLocatorPort,
        MoveExecutionEvent,
        MoveExecutorPolicy,
    )

    notices = TerminalEventSink()
    permissions = PermissionController()
    application_host = AppKitHost()
    chess = ChessApplicationController()
    window_locator = ChessWindowLocator()
    overlay = BoardOverlay()
    accessibility_probe = ChessBoardAccessibilityProbe()
    game_state = ChessStateObserver(
        ChessAccessibilitySnapshotProbe(accessibility_probe)
    )
    detector = FixedCalibrationDetector(
        chess,
        window_locator,
        accessibility_probe,
    )
    tracking_policy = BoardTrackingPolicy(
        minimum_confidence=STANDARD_SAFETY_POLICY.minimum_board_confidence,
        required_stable_detections=STANDARD_SAFETY_POLICY.required_stable_detections,
        maximum_detection_age=STANDARD_SAFETY_POLICY.maximum_detection_age_seconds,
        maximum_corner_drift_fraction=STANDARD_SAFETY_POLICY.maximum_corner_drift_fraction,
    )
    tracking = BoardTrackingService(detector.detect, policy=tracking_policy)
    move_policy = MoveExecutorPolicy(
        minimum_board_confidence=STANDARD_SAFETY_POLICY.minimum_board_confidence,
        required_stable_detections=STANDARD_SAFETY_POLICY.required_stable_detections,
        maximum_detection_age=STANDARD_SAFETY_POLICY.maximum_detection_age_seconds,
        click_delay=STANDARD_SAFETY_POLICY.click_delay_seconds,
        activation_timeout=STANDARD_SAFETY_POLICY.activation_timeout_seconds,
    )

    def report_execution(event: MoveExecutionEvent) -> None:
        if event.validation is not None:
            notices.emit(
                RuntimeEvent(
                    RuntimeStage.CUA,
                    "validation_passed",
                    fields={"operation": event.validation.value},
                    severity=RuntimeEventSeverity.DEBUG,
                )
            )
            return
        posted = event.posted_event
        if posted is not None:
            notices.emit(
                RuntimeEvent(
                    RuntimeStage.CUA,
                    "event_posted",
                    fields={
                        "type": posted.kind.value,
                        "square": posted.square.notation,
                    },
                )
            )

    move_executor = ChessMoveExecutor(
        application_controller=cast(ChessApplicationControllerPort, chess),
        window_locator=cast(ChessWindowLocatorPort, window_locator),
        board_tracker=tracking,
        event_poster=CGEventPoster(),
        display_contains_board=_display_contains_board,
        postcondition=ChessMovePostcondition(accessibility_probe),
        snapshot_probe=accessibility_probe,
        square_resolver=accessibility_probe,
        policy=move_policy,
        reporter=report_execution,
    )
    asr = ASRSupervisor(
        client_factory=lambda: VoiceASRClient(
            mode=Mode.ENDPOINTING,
            keywords=CHESS_ASR_KEYWORDS,
        )
    )
    runtime = VoiceCUARuntime(
        RuntimeDependencies(
            settings=FixedSettingsProvider(),
            credentials=EnvironmentRuntimeCredentialProvider(),
            permissions=permissions,
            chess=chess,
            tracking=tracking,
            overlay=overlay,
            asr=asr,
            audio=AudioCaptureService(),
            application_host=application_host,
            move_executor=move_executor,
            notices=notices,
            game_state=game_state,
        ),
        dry_run=dry_run,
    )
    return LiveRuntimeComponents(runtime, application_host)


def _display_contains_board(quad: Quad) -> bool:
    from voice_chess_cua.macos.native import load_framework

    quartz = load_framework("Quartz")
    error, display_ids, _count = quartz.CGGetActiveDisplayList(64, None, None)
    if int(error) != 0:
        return False
    for display_id in display_ids:
        bounds = quartz.CGDisplayBounds(display_id)
        minimum_x = float(bounds.origin.x)
        minimum_y = float(bounds.origin.y)
        maximum_x = minimum_x + float(bounds.size.width)
        maximum_y = minimum_y + float(bounds.size.height)
        if all(
            minimum_x <= point.x <= maximum_x and minimum_y <= point.y <= maximum_y
            for point in quad.points
        ):
            return True
    return False


ProcessFactory = Callable[[bool], RuntimeProcess]


class VoiceCUACommandServices:
    def __init__(self, *, process_factory: ProcessFactory | None = None) -> None:
        self._process_factory = process_factory or _build_runtime_process

    def execute(self, invocation: CLIInvocation) -> int:
        if invocation.command.name is CommandName.RUN:
            command = invocation.command
            return self._process_factory(command.dry_run).run()
        if invocation.command.name is CommandName.REQUEST_PERMISSIONS:
            return asyncio.run(_request_permissions())
        return int(CLIExitCode.USAGE)


async def _request_permissions() -> int:
    snapshot = await PermissionController().request_missing()
    print(
        "Permissions: "
        f"microphone={snapshot.microphone.value}, "
        f"accessibility={snapshot.accessibility.value}, "
        f"screen_recording={snapshot.screen_recording.value}"
    )
    if snapshot.all_granted:
        return int(CLIExitCode.SUCCESS)
    print(
        "Open System Settings > Privacy & Security, grant the missing permissions "
        "to this terminal or Python host, then restart it."
    )
    return int(CLIExitCode.PERMISSION)


def _build_runtime_process(dry_run: bool) -> RuntimeProcess:
    components = build_live_runtime(dry_run=dry_run)
    return AppKitRuntimeProcess(components.runtime, components.application_host)


def build_command_services() -> VoiceCUACommandServices:
    return VoiceCUACommandServices()
