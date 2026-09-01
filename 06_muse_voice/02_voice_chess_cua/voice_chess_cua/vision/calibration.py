# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Fixed calibration for the supported Apple Chess window layout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from voice_chess_cua.domain.geometry import PixelSize, Point, Quad


class CalibrationError(ValueError):
    pass


class UnsupportedAspectRatioError(CalibrationError):
    def __init__(self, actual: float, expected: float, tolerance: float) -> None:
        self.actual = actual
        self.expected = expected
        self.tolerance = tolerance
        super().__init__(
            "The Chess window layout does not match the calibrated demo. "
            f"Aspect ratio {actual:.3f} must be within {tolerance * 100:.0f}% "
            f"of {expected:.3f}."
        )


class InvalidCalibrationQuadError(CalibrationError):
    def __init__(self) -> None:
        super().__init__("The calibrated Chess board region is invalid.")


@dataclass(frozen=True, slots=True)
class AppleChessBoardCalibration:
    reference_image_size: PixelSize
    normalized_quad: Quad
    maximum_aspect_ratio_error: float

    current: ClassVar[AppleChessBoardCalibration]

    @property
    def reference_aspect_ratio(self) -> float:
        return self.reference_image_size.width / self.reference_image_size.height

    def image_quad(self, image_size: PixelSize) -> Quad:
        aspect_ratio = image_size.width / image_size.height
        relative_error = (
            abs(aspect_ratio - self.reference_aspect_ratio)
            / self.reference_aspect_ratio
        )
        if relative_error > self.maximum_aspect_ratio_error:
            raise UnsupportedAspectRatioError(
                aspect_ratio,
                self.reference_aspect_ratio,
                self.maximum_aspect_ratio_error,
            )
        width = float(image_size.width)
        height = float(image_size.height)
        try:
            quad = Quad(
                self._scale(self.normalized_quad.top_left, width, height),
                self._scale(self.normalized_quad.top_right, width, height),
                self._scale(self.normalized_quad.bottom_right, width, height),
                self._scale(self.normalized_quad.bottom_left, width, height),
            )
        except ValueError as error:
            raise InvalidCalibrationQuadError() from error
        if not all(
            0 <= point.x <= width and 0 <= point.y <= height for point in quad.points
        ):
            raise InvalidCalibrationQuadError()
        return quad

    @staticmethod
    def _scale(point: Point, width: float, height: float) -> Point:
        return Point(point.x * width, point.y * height)


AppleChessBoardCalibration.current = AppleChessBoardCalibration(
    reference_image_size=PixelSize(979, 768),
    normalized_quad=Quad(
        Point(263.0 / 979.0, 198.0 / 768.0),
        Point(714.0 / 979.0, 198.0 / 768.0),
        Point(777.0 / 979.0, 650.0 / 768.0),
        Point(201.0 / 979.0, 650.0 / 768.0),
    ),
    maximum_aspect_ratio_error=0.03,
)

CURRENT_CALIBRATION = AppleChessBoardCalibration.current
