# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from voice_chess_cua.cli import CLICommand, CLIInvocation, CommandName
from voice_chess_cua.domain.chess import BoardOrientation, ChessSquare
from voice_chess_cua.domain.geometry import BoardGeometry, Point, Rect
from voice_chess_cua.macos.application import ChessApplicationStatus
from voice_chess_cua.macos.permissions import PermissionGrant, PermissionSnapshot
from voice_chess_cua.macos.windows import ChessWindowDescriptor
from voice_chess_cua.runtime.ports import RuntimeCredentials
from voice_chess_cua.runtime.services import (
    EnvironmentRuntimeCredentialProvider,
    FixedCalibrationDetector,
    VoiceCUACommandServices,
    _request_permissions,
)
from voice_chess_cua.vision.calibration import AppleChessBoardCalibration
from voice_chess_cua.vision.tracking import BoardDetectionError

_REFERENCE_FRAME = Rect(100, 200, 979, 768)
_DETECTED_AT = datetime(2026, 8, 23, tzinfo=UTC)

# Frames and landmarks captured together from two live Apple Chess windows.
# Apple Chess reports landmark positions with the vertical axis inverted, so
# these only agree with the calibrated quad on the distances between landmarks.
_LIVE_FRAME = Rect(8.0, 446.0, 852.0, 671.0)
_LIVE_LANDMARKS = {
    "a8": Point(259.3598403930664, 948.742790222168),
    "h8": Point(608.6401062011719, 948.7428359985352),
    "a1": Point(222.91900634765625, 614.0659027099609),
    "h1": Point(645.0810241699219, 614.0659790039062),
}
_WIDE_LIVE_FRAME = Rect(8.0, 142.0, 1257.0, 975.0)
_WIDE_LIVE_LANDMARKS = {
    "a8": Point(378.64, 868.81),
    "h8": Point(894.35, 868.81),
    "a1": Point(324.85, 374.67),
    "h1": Point(948.16, 374.67),
}


class ProcessFake:
    def __init__(self) -> None:
        self.runs = 0

    def run(self) -> int:
        self.runs += 1
        return 0


class PermissionControllerFake:
    def __init__(self, snapshot: PermissionSnapshot) -> None:
        self.snapshot = snapshot
        self.request_count = 0

    async def request_missing(self) -> PermissionSnapshot:
        self.request_count += 1
        return self.snapshot


class LandmarkProbeFake:
    def __init__(self, centers: dict[str, Point]) -> None:
        self.centers = centers
        self.process_identifiers: list[int] = []

    async def square_centers(self, process_identifier: int) -> dict[str, Point]:
        self.process_identifiers.append(process_identifier)
        return self.centers


class ChessFake:
    def __init__(
        self,
        *,
        bound_process_identifier: int | None = 42,
        status: ChessApplicationStatus | None = None,
    ) -> None:
        self._bound_process_identifier = bound_process_identifier
        self._status = status or ChessApplicationStatus(True, True, 42)

    @property
    def bound_process_identifier(self) -> int | None:
        return self._bound_process_identifier

    async def status(self) -> ChessApplicationStatus:
        return self._status


class Locator:
    def __init__(self, window: ChessWindowDescriptor) -> None:
        self._window = window

    async def locate(
        self, expected_process_id: int | None = None
    ) -> ChessWindowDescriptor:
        assert expected_process_id == 42
        return self._window


def make_window(
    *,
    title: str = "Chess",
    frame: Rect = _REFERENCE_FRAME,
    process_id: int = 42,
) -> ChessWindowDescriptor:
    return ChessWindowDescriptor(
        window_id=77,
        frame=frame,
        title=title,
        application_name="Chess",
        process_id=process_id,
    )


def landmarks(frame: Rect = _REFERENCE_FRAME) -> dict[str, Point]:
    """Landmarks whose horizontal spread agrees with the calibrated quad."""

    geometry = BoardGeometry(
        AppleChessBoardCalibration.current.window_quad(frame),
        BoardOrientation.WHITE_BOTTOM,
    )
    return {
        square: geometry.center_of(ChessSquare.parse(square.upper()))
        for square in ("a1", "h1", "a8", "h8")
    }


def make_detector(
    centers: dict[str, Point] | None = None,
    *,
    window: ChessWindowDescriptor | None = None,
    chess: ChessFake | None = None,
) -> tuple[FixedCalibrationDetector, LandmarkProbeFake]:
    window = window or make_window()
    probe = LandmarkProbeFake(
        centers if centers is not None else landmarks(window.frame)
    )
    detector = FixedCalibrationDetector(
        chess or ChessFake(),  # type: ignore[arg-type]
        Locator(window),  # type: ignore[arg-type]
        probe,  # type: ignore[arg-type]
        clock=lambda: _DETECTED_AT,
    )
    return detector, probe


def test_command_services_forward_dry_run_to_process_factory() -> None:
    calls: list[bool] = []
    process = ProcessFake()

    def factory(dry_run: bool) -> ProcessFake:
        calls.append(dry_run)
        return process

    services = VoiceCUACommandServices(process_factory=factory)
    result = services.execute(CLIInvocation(CLICommand(CommandName.RUN, dry_run=True)))

    assert result == 0
    assert calls == [True]
    assert process.runs == 1


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (
            PermissionSnapshot(
                PermissionGrant.GRANTED,
                PermissionGrant.GRANTED,
                PermissionGrant.GRANTED,
            ),
            0,
        ),
        (
            PermissionSnapshot(
                PermissionGrant.GRANTED,
                PermissionGrant.GRANTED,
                PermissionGrant.DENIED,
            ),
            4,
        ),
    ],
)
def test_permission_request_returns_status_from_resulting_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: PermissionSnapshot,
    expected: int,
) -> None:
    controller = PermissionControllerFake(snapshot)
    monkeypatch.setattr(
        "voice_chess_cua.runtime.services.PermissionController",
        lambda: controller,
    )

    assert asyncio.run(_request_permissions()) == expected
    assert controller.request_count == 1


def test_runtime_credentials_use_only_model_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "  model-secret  ")

    credentials = asyncio.run(
        EnvironmentRuntimeCredentialProvider().load_runtime_credentials()
    )

    assert credentials == RuntimeCredentials(model_api_key="model-secret")


def test_runtime_credentials_require_nonempty_model_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "  ")

    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        asyncio.run(EnvironmentRuntimeCredentialProvider().load_runtime_credentials())


def test_detector_places_calibrated_quad_in_the_reference_window() -> None:
    detector, probe = make_detector()

    detection = asyncio.run(detector.detect())

    assert detection.confidence == 0.99
    assert detection.captured_at == _DETECTED_AT
    assert detection.source_window_id == 77
    assert detection.geometry.quad.top_left == Point(363.0, 398.0)
    assert detection.geometry.quad.bottom_left == Point(301.0, 850.0)
    assert probe.process_identifiers == [42]


def test_detector_keeps_the_board_narrower_at_the_back() -> None:
    detector, _ = make_detector()

    quad = asyncio.run(detector.detect()).geometry.quad
    back_width = quad.top_right.x - quad.top_left.x
    front_width = quad.bottom_right.x - quad.bottom_left.x

    assert back_width == pytest.approx(451.0)
    assert front_width == pytest.approx(576.0)


@pytest.mark.parametrize(
    ("frame", "centers"),
    (
        (_LIVE_FRAME, _LIVE_LANDMARKS),
        (_WIDE_LIVE_FRAME, _WIDE_LIVE_LANDMARKS),
    ),
)
def test_detector_agrees_with_landmarks_measured_on_live_windows(
    frame: Rect,
    centers: dict[str, Point],
) -> None:
    detector, _ = make_detector(centers, window=make_window(frame=frame))

    geometry = asyncio.run(detector.detect()).geometry

    for start, end in (("a1", "h1"), ("a8", "h8"), ("a1", "a8"), ("h1", "h8")):
        calibrated = geometry.center_of(ChessSquare.parse(start.upper())).distance_to(
            geometry.center_of(ChessSquare.parse(end.upper()))
        )
        measured = centers[start].distance_to(centers[end])
        assert calibrated == pytest.approx(measured, rel=0.04)


def test_detector_scales_the_board_with_the_window() -> None:
    detector, _ = make_detector(
        _LIVE_LANDMARKS,
        window=make_window(frame=_LIVE_FRAME),
    )

    quad = asyncio.run(detector.detect()).geometry.quad

    assert quad.top_left.y == pytest.approx(619.0, abs=0.5)
    assert quad.bottom_left.y == pytest.approx(1013.9, abs=0.5)
    assert quad.top_left.x == pytest.approx(236.9, abs=0.5)
    assert quad.bottom_right.x == pytest.approx(684.2, abs=0.5)


def test_detector_accepts_landmarks_whose_ranks_are_reported_mirrored() -> None:
    """Apple Chess reports square frames on the vertically reflected rank."""

    centers = landmarks(_REFERENCE_FRAME)
    axis = sum(center.y for center in centers.values()) / 4
    mirrored = {
        square: Point(center.x, 2.0 * axis - center.y)
        for square, center in centers.items()
    }
    detector, _ = make_detector(mirrored)

    assert asyncio.run(detector.detect()).geometry.quad.top_left == Point(363.0, 398.0)


def test_detector_rejects_black_at_bottom_landmarks() -> None:
    centers = landmarks(_REFERENCE_FRAME)
    flipped = {
        "a1": Point(centers["a8"].x, centers["a1"].y),
        "h1": Point(centers["h8"].x, centers["h1"].y),
        "a8": Point(centers["a1"].x, centers["a8"].y),
        "h8": Point(centers["h1"].x, centers["h8"].y),
    }
    detector, _ = make_detector(flipped)

    with pytest.raises(BoardDetectionError, match="unsupported_orientation"):
        asyncio.run(detector.detect())


def test_detector_rejects_landmarks_wider_than_the_calibrated_quad() -> None:
    centers = landmarks(_REFERENCE_FRAME)
    centers["h1"] = Point(centers["h1"].x + 60.0, centers["h1"].y)
    detector, _ = make_detector(centers)

    with pytest.raises(BoardDetectionError, match="layout_mismatch"):
        asyncio.run(detector.detect())


def test_detector_rejects_incomplete_landmarks() -> None:
    centers = landmarks(_REFERENCE_FRAME)
    del centers["h8"]
    detector, _ = make_detector(centers)

    with pytest.raises(BoardDetectionError, match="layout_mismatch"):
        asyncio.run(detector.detect())


def test_detector_rejects_landmarks_outside_the_chess_window() -> None:
    centers = {
        square: Point(center.x - 400.0, center.y)
        for square, center in landmarks(_REFERENCE_FRAME).items()
    }
    detector, _ = make_detector(centers)

    with pytest.raises(BoardDetectionError, match="layout_mismatch"):
        asyncio.run(detector.detect())


def test_detector_rejects_windows_outside_the_calibrated_aspect_ratio() -> None:
    detector, _ = make_detector(
        landmarks(_REFERENCE_FRAME),
        window=make_window(frame=Rect(100, 200, 979, 600)),
    )

    with pytest.raises(BoardDetectionError, match="unsupported_aspect"):
        asyncio.run(detector.detect())


def test_detector_rejects_auto_rotating_human_game() -> None:
    detector, _ = make_detector(
        window=make_window(title="Game 2 | Auto-Match Player (White to Move)")
    )

    with pytest.raises(BoardDetectionError, match="layout_mismatch"):
        asyncio.run(detector.detect())


def test_detector_rejects_current_pid_different_from_bound_pid() -> None:
    detector, _ = make_detector(
        chess=ChessFake(
            bound_process_identifier=42,
            status=ChessApplicationStatus(True, True, 43),
        )
    )

    with pytest.raises(BoardDetectionError, match="window_unavailable"):
        asyncio.run(detector.detect())


def test_detector_requires_a_bound_process_identifier() -> None:
    detector, _ = make_detector(chess=ChessFake(bound_process_identifier=None))

    with pytest.raises(BoardDetectionError, match="window_unavailable"):
        asyncio.run(detector.detect())
