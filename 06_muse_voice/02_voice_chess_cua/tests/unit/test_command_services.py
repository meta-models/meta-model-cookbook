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
from voice_chess_cua.domain.chess import ChessSquare
from voice_chess_cua.domain.geometry import PixelSize, Point, Rect
from voice_chess_cua.macos.application import ChessApplicationStatus
from voice_chess_cua.macos.capture import WindowScreenshot
from voice_chess_cua.macos.permissions import PermissionGrant, PermissionSnapshot
from voice_chess_cua.macos.windows import ChessWindowDescriptor
from voice_chess_cua.runtime.ports import RuntimeCredentials
from voice_chess_cua.runtime.services import (
    EnvironmentRuntimeCredentialProvider,
    FixedCalibrationDetector,
    VoiceCUACommandServices,
    _reconcile_accessibility_geometry,
    _request_permissions,
)

_CALIBRATED_WINDOW_FRAME = Rect(100, 200, 979, 768)


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

    async def square_centers(self, process_identifier: int) -> dict[str, Point]:
        assert process_identifier == 42
        return self.centers


class ChessFake:
    async def status(self) -> ChessApplicationStatus:
        return ChessApplicationStatus(True, False, 42)


class Locator:
    def __init__(self, window: ChessWindowDescriptor) -> None:
        self._window = window

    async def locate(
        self, expected_process_id: int | None = None
    ) -> ChessWindowDescriptor:
        assert expected_process_id == 42
        return self._window


class Provider:
    def __init__(self, screenshot: WindowScreenshot) -> None:
        self._screenshot = screenshot

    async def capture(self, window_id: int) -> WindowScreenshot:
        assert window_id == self._screenshot.window.window_id
        return self._screenshot


def make_screenshot(
    *, title: str = "Chess", frame: Rect = _CALIBRATED_WINDOW_FRAME
) -> WindowScreenshot:
    window = ChessWindowDescriptor(
        window_id=77,
        frame=frame,
        title=title,
        application_name="Chess",
        process_id=42,
        is_frontmost=True,
        display_ids=(1,),
    )
    return WindowScreenshot(
        image=object(),
        window=window,
        image_size=PixelSize(round(frame.width), round(frame.height)),
        point_pixel_scale_x=1.0,
        point_pixel_scale_y=1.0,
        captured_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def make_detector(
    screenshot: WindowScreenshot,
    *,
    white_bottom: bool = True,
    matching_layout: bool = True,
) -> FixedCalibrationDetector:
    async def orientation_checker(_image: object, _quad: object) -> bool:
        return white_bottom

    async def layout_checker(
        process_identifier: int,
        geometry: object,
        window_frame: Rect,
    ) -> object | None:
        assert process_identifier == 42
        assert window_frame == screenshot.window.frame
        return geometry if matching_layout else None

    return FixedCalibrationDetector(
        ChessFake(),  # type: ignore[arg-type]
        Locator(screenshot.window),  # type: ignore[arg-type]
        Provider(screenshot),  # type: ignore[arg-type]
        orientation_checker=orientation_checker,  # type: ignore[arg-type]
        layout_checker=layout_checker,  # type: ignore[arg-type]
    )


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


def test_fixed_detector_maps_979_by_768_calibration_to_global_window() -> None:
    detection = asyncio.run(make_detector(make_screenshot()).detect())

    assert detection.confidence == 0.99
    assert detection.proposal_score == 1.0
    assert detection.source_window_id == 77
    assert detection.geometry.quad.top_left == Point(363.0, 398.0)


def test_fixed_detector_rejects_black_at_bottom_orientation() -> None:
    detector = make_detector(make_screenshot(), white_bottom=False)

    with pytest.raises(Exception, match="unsupported_orientation"):
        asyncio.run(detector.detect())


def test_fixed_detector_rejects_layout_without_matching_ax_landmarks() -> None:
    detector = make_detector(make_screenshot(), matching_layout=False)

    with pytest.raises(Exception, match="layout_mismatch"):
        asyncio.run(detector.detect())


def test_ax_layout_accepts_uniformly_translated_landmarks() -> None:
    detection = asyncio.run(make_detector(make_screenshot()).detect())
    geometry = detection.geometry
    expected = {
        square: geometry.center_of(ChessSquare.parse(square.upper()))
        for square in ("a1", "h1", "a8", "h8")
    }
    shifted = {
        square: Point(center.x + 50.0, center.y + 25.0)
        for square, center in expected.items()
    }

    corrected = asyncio.run(
        _reconcile_accessibility_geometry(
            LandmarkProbeFake(shifted),  # type: ignore[arg-type]
            42,
            geometry,
            _CALIBRATED_WINDOW_FRAME,
        )
    )

    assert corrected == geometry


@pytest.mark.parametrize(
    "changed_square",
    ("a1", "h1", "a8", "h8"),
)
def test_ax_layout_rejects_nonuniform_landmark_offsets(changed_square: str) -> None:
    detection = asyncio.run(make_detector(make_screenshot()).detect())
    geometry = detection.geometry
    centers = {
        square: geometry.center_of(ChessSquare.parse(square.upper()))
        for square in ("a1", "h1", "a8", "h8")
    }
    center = centers[changed_square]
    centers[changed_square] = Point(center.x + 100.0, center.y)

    assert (
        asyncio.run(
            _reconcile_accessibility_geometry(
                LandmarkProbeFake(centers),  # type: ignore[arg-type]
                42,
                geometry,
                _CALIBRATED_WINDOW_FRAME,
            )
        )
        is None
    )


def test_fixed_detector_rejects_auto_rotating_human_game() -> None:
    screenshot = make_screenshot(
        title="Game 2 | Voice CUA - Auto-Match Player (White to Move)"
    )

    with pytest.raises(Exception, match="layout_mismatch"):
        asyncio.run(make_detector(screenshot).detect())
