# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Default CLI services and live Voice CUA object composition."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from math import hypot, isfinite
from statistics import median
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
from voice_chess_cua.macos._main_thread import run_on_main
from voice_chess_cua.macos.appkit_host import AppKitHost
from voice_chess_cua.macos.application import ChessApplicationController
from voice_chess_cua.macos.audio import AudioCaptureService
from voice_chess_cua.macos.capture import (
    WindowCaptureTimedOutError,
    WindowScreenshotProvider,
    WindowUnavailableError,
)
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
from voice_chess_cua.planning.exact_parser import ExactMoveParser
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
from voice_chess_cua.vision.coordinates import ScreenCoordinateMapper
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


class UnsupportedBoardOrientationError(RuntimeError):
    pass


class BoardLayoutMismatchError(RuntimeError):
    pass


OrientationChecker = Callable[[object, Quad], Awaitable[bool]]
LayoutChecker = Callable[[int, BoardGeometry, Rect], Awaitable[BoardGeometry | None]]


class FixedCalibrationDetector:
    """Capture the unique Chess window and map the fixed board quad to global CG space."""

    def __init__(
        self,
        application: ChessApplicationController,
        window_locator: ChessWindowLocator,
        screenshot_provider: WindowScreenshotProvider,
        calibration: AppleChessBoardCalibration = AppleChessBoardCalibration.current,
        orientation_checker: OrientationChecker | None = None,
        layout_checker: LayoutChecker | None = None,
    ) -> None:
        self._application = application
        self._window_locator = window_locator
        self._screenshot_provider = screenshot_provider
        self._calibration = calibration
        self._orientation_checker = (
            orientation_checker or _captured_board_is_white_bottom
        )
        probe = ChessBoardAccessibilityProbe()
        self._layout_checker = layout_checker or (
            lambda process_identifier, geometry, window_frame: (
                _reconcile_accessibility_geometry(
                    probe,
                    process_identifier,
                    geometry,
                    window_frame,
                )
            )
        )

    async def detect(self) -> BoardDetection:
        application = await self._application.status()
        if not application.is_running or application.process_identifier is None:
            raise RuntimeError("Chess.app is not running.")
        try:
            window = await self._window_locator.locate(application.process_identifier)
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
        try:
            screenshot = await self._screenshot_provider.capture(window.window_id)
        except ScreenCaptureKitError as error:
            raise BoardDetectionError(_screen_capture_reason(error)) from error
        except ShareableContentTimedOutError as error:
            raise BoardDetectionError(
                TrackingFailureReason.WINDOW_DISCOVERY_TIMEOUT
            ) from error
        except WindowCaptureTimedOutError as error:
            raise BoardDetectionError(TrackingFailureReason.CAPTURE_TIMEOUT) from error
        except WindowUnavailableError as error:
            raise BoardDetectionError(
                TrackingFailureReason.WINDOW_UNAVAILABLE
            ) from error
        if "Auto-Match Player" in (screenshot.window.title or ""):
            raise BoardDetectionError(TrackingFailureReason.LAYOUT_MISMATCH)
        if screenshot.window.process_id != application.process_identifier:
            raise BoardDetectionError(TrackingFailureReason.WINDOW_UNAVAILABLE)
        try:
            image_quad = self._calibration.image_quad(screenshot.image_size)
        except UnsupportedAspectRatioError as error:
            raise BoardDetectionError(
                TrackingFailureReason.UNSUPPORTED_ASPECT
            ) from error
        except CalibrationError as error:
            raise BoardDetectionError(TrackingFailureReason.DETECTION_FAILED) from error
        if not await self._orientation_checker(screenshot.image, image_quad):
            error = UnsupportedBoardOrientationError(
                "The calibrated board is not confidently White-at-bottom."
            )
            raise BoardDetectionError(
                TrackingFailureReason.UNSUPPORTED_ORIENTATION
            ) from error
        mapper = ScreenCoordinateMapper(
            captured_image_size=screenshot.image_size,
            captured_global_frame=screenshot.window.frame,
            primary_screen_max_y=0.0,
        )
        global_quad = Quad(
            *(mapper.global_cg_from_captured(point) for point in image_quad.points)
        )
        geometry = BoardGeometry(global_quad, BoardOrientation.WHITE_BOTTOM)
        try:
            corrected_geometry = await self._layout_checker(
                application.process_identifier,
                geometry,
                screenshot.window.frame,
            )
        except BoardDetectionError:
            raise
        except Exception as error:
            raise BoardDetectionError(TrackingFailureReason.LAYOUT_MISMATCH) from error
        if corrected_geometry is None:
            raise BoardDetectionError(TrackingFailureReason.LAYOUT_MISMATCH)
        return BoardDetection(
            geometry=corrected_geometry,
            confidence=0.99,
            proposal_score=1.0,
            captured_at=screenshot.captured_at,
            source_window_id=screenshot.window.window_id,
        )


async def _reconcile_accessibility_geometry(
    probe: ChessBoardAccessibilityProbe,
    process_identifier: int,
    geometry: BoardGeometry,
    window_frame: Rect,
) -> BoardGeometry | None:
    centers = await probe.square_centers(process_identifier)
    landmark_names = ("a1", "h1", "a8", "h8")
    if set(centers) != set(landmark_names):
        return None
    expected = {
        square: geometry.center_of(ChessSquare.parse(square.upper()))
        for square in landmark_names
    }
    expected_distances = _landmark_distances(expected)
    actual_distances = _landmark_distances(centers)
    if expected_distances.keys() != actual_distances.keys() or not all(
        abs(actual_distances[pair] - expected_distance) / expected_distance <= 0.08
        for pair, expected_distance in expected_distances.items()
    ):
        return None
    try:
        corrected = _geometry_from_accessibility_centers(centers, geometry.orientation)
    except ValueError:
        return None
    board_span = max(corrected.quad.width, corrected.quad.height)
    maximum_residual = max(1.0, board_span * 0.005)
    if any(
        corrected.center_of(ChessSquare.parse(square.upper())).distance_to(center)
        > maximum_residual
        for square, center in centers.items()
    ):
        return None
    rounding_tolerance = max(1.0, board_span * 0.005)
    if any(
        not (
            window_frame.min_x - rounding_tolerance
            <= point.x
            <= window_frame.max_x + rounding_tolerance
            and window_frame.min_y - rounding_tolerance
            <= point.y
            <= window_frame.max_y + rounding_tolerance
        )
        for point in corrected.quad.points
    ):
        return None
    return corrected


def _geometry_from_accessibility_centers(
    centers: Mapping[str, Point],
    orientation: BoardOrientation,
) -> BoardGeometry:
    unit_centers = {
        "a8": Point(1.0 / 16.0, 1.0 / 16.0),
        "h8": Point(15.0 / 16.0, 1.0 / 16.0),
        "h1": Point(15.0 / 16.0, 15.0 / 16.0),
        "a1": Point(1.0 / 16.0, 15.0 / 16.0),
    }
    if set(centers) != set(unit_centers):
        raise ValueError("Accessibility board landmarks are incomplete")
    coefficients = _solve_homography(
        tuple((unit_centers[square], centers[square]) for square in unit_centers)
    )

    def mapped(point: Point) -> Point:
        a, b, c, d, e, f, g, h = coefficients
        denominator = g * point.x + h * point.y + 1.0
        if not isfinite(denominator) or abs(denominator) <= 1e-12:
            raise ValueError("Accessibility board homography maps to infinity")
        result = Point(
            (a * point.x + b * point.y + c) / denominator,
            (d * point.x + e * point.y + f) / denominator,
        )
        if not result.is_finite:
            raise ValueError("Accessibility board homography is not finite")
        return result

    return BoardGeometry(
        Quad(
            mapped(Point(0.0, 0.0)),
            mapped(Point(1.0, 0.0)),
            mapped(Point(1.0, 1.0)),
            mapped(Point(0.0, 1.0)),
        ),
        orientation,
    )


def _solve_homography(
    correspondences: tuple[tuple[Point, Point], ...],
) -> tuple[float, float, float, float, float, float, float, float]:
    if len(correspondences) != 4:
        raise ValueError("A homography requires four point correspondences")
    matrix: list[list[float]] = []
    for source, destination in correspondences:
        x, y = source.x, source.y
        target_x, target_y = destination.x, destination.y
        matrix.append(
            [x, y, 1.0, 0.0, 0.0, 0.0, -target_x * x, -target_x * y, target_x]
        )
        matrix.append(
            [0.0, 0.0, 0.0, x, y, 1.0, -target_y * x, -target_y * y, target_y]
        )
    size = 8
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(matrix[row][column]))
        pivot_value = matrix[pivot][column]
        if not isfinite(pivot_value) or abs(pivot_value) <= 1e-12:
            raise ValueError("Accessibility board homography is singular")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(size):
            if row == column:
                continue
            factor = matrix[row][column]
            if factor == 0.0:
                continue
            matrix[row] = [
                value - factor * normalized_value
                for value, normalized_value in zip(
                    matrix[row], matrix[column], strict=True
                )
            ]
    solution = tuple(matrix[row][-1] for row in range(size))
    if len(solution) != size or not all(isfinite(value) for value in solution):
        raise ValueError("Accessibility board homography is not finite")
    return cast(
        tuple[float, float, float, float, float, float, float, float],
        solution,
    )


def _screen_capture_reason(error: ScreenCaptureKitError) -> TrackingFailureReason:
    if error.code == -3801:
        return TrackingFailureReason.SCREEN_CAPTURE_PERMISSION
    return TrackingFailureReason.DETECTION_FAILED


def _landmark_distances(centers: Mapping[str, Point]) -> dict[tuple[str, str], float]:
    pairs = (("a1", "h1"), ("a8", "h8"), ("a1", "a8"), ("h1", "h8"))
    return {
        pair: hypot(
            centers[pair[0]].x - centers[pair[1]].x,
            centers[pair[0]].y - centers[pair[1]].y,
        )
        for pair in pairs
        if pair[0] in centers and pair[1] in centers
    }


async def _captured_board_is_white_bottom(image: object, image_quad: Quad) -> bool:
    return await run_on_main(
        lambda: _sample_white_bottom_orientation(image, image_quad)
    )


def _sample_white_bottom_orientation(image: object, image_quad: Quad) -> bool:
    from voice_chess_cua.macos._native import load_framework

    appkit = load_framework("AppKit")
    bitmap = appkit.NSBitmapImageRep.alloc().initWithCGImage_(image)
    if bitmap is None:
        return False
    geometry = BoardGeometry(image_quad, BoardOrientation.WHITE_BOTTOM)
    xs = tuple(point.x for point in image_quad.points)
    ys = tuple(point.y for point in image_quad.points)
    cell_width = max((max(xs) - min(xs)) / 8.0, 1.0)
    cell_height = max((max(ys) - min(ys)) / 8.0, 1.0)
    bottom = _rank_brightness(bitmap, appkit, geometry, 1, cell_width, cell_height)
    top = _rank_brightness(bitmap, appkit, geometry, 8, cell_width, cell_height)
    if bottom is None or top is None:
        return False
    return bottom - top >= 0.15


def _rank_brightness(
    bitmap: object,
    appkit: object,
    geometry: BoardGeometry,
    rank: int,
    cell_width: float,
    cell_height: float,
) -> float | None:
    samples: list[float] = []
    offsets_x = (-0.09 * cell_width, 0.0, 0.09 * cell_width)
    offsets_y = (-0.09 * cell_height, 0.0, 0.09 * cell_height)
    color_space = appkit.NSColorSpace.deviceRGBColorSpace()  # type: ignore[attr-defined]
    for file_index in range(8):
        center = geometry.center_of(ChessSquare(file_index, rank))
        square_samples: list[float] = []
        for offset_x in offsets_x:
            for offset_y in offsets_y:
                color = bitmap.colorAtX_y_(  # type: ignore[attr-defined]
                    round(center.x + offset_x),
                    round(center.y + offset_y),
                )
                if color is None:
                    continue
                converted = color.colorUsingColorSpace_(color_space)
                if converted is not None:
                    square_samples.append(float(converted.brightnessComponent()))
        if square_samples:
            samples.append(median(square_samples))
    return median(samples) if len(samples) == 8 else None


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
    screenshot_provider = WindowScreenshotProvider()
    overlay = BoardOverlay()
    accessibility_probe = ChessBoardAccessibilityProbe()
    game_state = ChessStateObserver(
        ChessAccessibilitySnapshotProbe(accessibility_probe)
    )
    detector = FixedCalibrationDetector(
        chess,
        window_locator,
        screenshot_provider,
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
            planner=ExactMoveParser(),
            application_host=application_host,
            snapshot_probe=accessibility_probe,
            move_executor=move_executor,
            notices=notices,
            game_state=game_state,
        ),
        dry_run=dry_run,
    )
    return LiveRuntimeComponents(runtime, application_host)


def _display_contains_board(quad: Quad) -> bool:
    from voice_chess_cua.macos._native import load_framework

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
