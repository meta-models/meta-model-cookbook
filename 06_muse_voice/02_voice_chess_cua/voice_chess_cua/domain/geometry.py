# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Pure projective geometry for the calibrated Chess board."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import hypot, isfinite

from voice_chess_cua.domain.chess import BoardOrientation, ChessSquare


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    @property
    def is_finite(self) -> bool:
        return isfinite(self.x) and isfinite(self.y)

    def distance_to(self, other: Point) -> float:
        return hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True, slots=True)
class PixelSize:
    width: int
    height: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.width, bool)
            or isinstance(self.height, bool)
            or not isinstance(self.width, int)
            or not isinstance(self.height, int)
            or self.width <= 0
            or self.height <= 0
        ):
            raise ValueError("pixel dimensions must be positive integers")


@dataclass(frozen=True, slots=True)
class Rect:
    """A rectangle in top-left-origin, y-down coordinates."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if not all(
            isfinite(value) for value in (self.x, self.y, self.width, self.height)
        ):
            raise ValueError("rectangle values must be finite")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle dimensions must be positive")

    @property
    def min_x(self) -> float:
        return self.x

    @property
    def max_x(self) -> float:
        return self.x + self.width

    @property
    def min_y(self) -> float:
        return self.y

    @property
    def max_y(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def contains(self, point: Point) -> bool:
        return (
            point.is_finite
            and self.min_x <= point.x <= self.max_x
            and self.min_y <= point.y <= self.max_y
        )


ScreenRect = Rect


@dataclass(frozen=True, slots=True)
class Quad:
    """A non-degenerate convex quadrilateral in boundary order."""

    top_left: Point
    top_right: Point
    bottom_right: Point
    bottom_left: Point

    def __post_init__(self) -> None:
        if not self._is_valid(self.points):
            raise ValueError(
                "quad corners must be finite and form a non-degenerate convex polygon"
            )

    @property
    def points(self) -> tuple[Point, Point, Point, Point]:
        return (self.top_left, self.top_right, self.bottom_right, self.bottom_left)

    @property
    def area(self) -> float:
        return abs(self._signed_double_area(self.points)) * 0.5

    @property
    def width(self) -> float:
        xs = tuple(point.x for point in self.points)
        return max(xs) - min(xs)

    @property
    def height(self) -> float:
        ys = tuple(point.y for point in self.points)
        return max(ys) - min(ys)

    @property
    def center(self) -> Point:
        return Point(
            sum(point.x for point in self.points) / 4,
            sum(point.y for point in self.points) / 4,
        )

    def contains(self, point: Point, tolerance: float = 1e-8) -> bool:
        if not point.is_finite:
            return False
        scale = max(self.width, self.height, 1.0)
        scaled_tolerance = tolerance * scale * scale
        sign = 0
        for index, start in enumerate(self.points):
            end = self.points[(index + 1) % 4]
            cross = self._cross(start, end, point)
            if abs(cross) <= scaled_tolerance:
                continue
            current_sign = 1 if cross > 0 else -1
            if sign == 0:
                sign = current_sign
            elif sign != current_sign:
                return False
        return True

    def maximum_corner_distance_to(self, other: Quad) -> float:
        return max(
            left.distance_to(right)
            for left, right in zip(self.points, other.points, strict=True)
        )

    @classmethod
    def _is_valid(cls, points: tuple[Point, Point, Point, Point]) -> bool:
        if not all(point.is_finite for point in points):
            return False
        xs = tuple(point.x for point in points)
        ys = tuple(point.y for point in points)
        scale = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        epsilon = scale * scale * 1e-9
        crosses = tuple(
            cls._cross(points[index], points[(index + 1) % 4], points[(index + 2) % 4])
            for index in range(4)
        )
        if not all(abs(cross) > epsilon for cross in crosses):
            return False
        if not (
            all(cross > 0 for cross in crosses) or all(cross < 0 for cross in crosses)
        ):
            return False
        return abs(cls._signed_double_area(points)) > epsilon

    @staticmethod
    def _cross(a: Point, b: Point, c: Point) -> float:
        return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

    @staticmethod
    def _signed_double_area(points: tuple[Point, ...]) -> float:
        return sum(
            point.x * points[(index + 1) % len(points)].y
            - points[(index + 1) % len(points)].x * point.y
            for index, point in enumerate(points)
        )


@dataclass(frozen=True, slots=True)
class _ProjectiveTransform:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float
    g: float
    h: float

    @classmethod
    def from_quad(cls, quad: Quad) -> _ProjectiveTransform:
        top_left = quad.top_left
        top_right = quad.top_right
        bottom_right = quad.bottom_right
        bottom_left = quad.bottom_left
        dx1 = top_right.x - bottom_right.x
        dx2 = bottom_left.x - bottom_right.x
        dx3 = top_left.x - top_right.x + bottom_right.x - bottom_left.x
        dy1 = top_right.y - bottom_right.y
        dy2 = bottom_left.y - bottom_right.y
        dy3 = top_left.y - top_right.y + bottom_right.y - bottom_left.y

        if abs(dx3) < 1e-12 and abs(dy3) < 1e-12:
            return cls(
                top_right.x - top_left.x,
                bottom_left.x - top_left.x,
                top_left.x,
                top_right.y - top_left.y,
                bottom_left.y - top_left.y,
                top_left.y,
                0.0,
                0.0,
            )

        denominator = dx1 * dy2 - dx2 * dy1
        if not isfinite(denominator) or abs(denominator) <= 1e-12:
            raise ValueError("quad does not define a finite projective transform")
        g = (dx3 * dy2 - dx2 * dy3) / denominator
        h = (dx1 * dy3 - dx3 * dy1) / denominator
        coefficients = (
            top_right.x - top_left.x + g * top_right.x,
            bottom_left.x - top_left.x + h * bottom_left.x,
            top_left.x,
            top_right.y - top_left.y + g * top_right.y,
            bottom_left.y - top_left.y + h * bottom_left.y,
            top_left.y,
            g,
            h,
        )
        if not all(isfinite(value) for value in coefficients):
            raise ValueError("quad does not define a finite projective transform")
        return cls(*coefficients)

    def map(self, unit_x: float, unit_y: float) -> Point:
        if not isfinite(unit_x) or not isfinite(unit_y):
            raise ValueError("unit coordinates must be finite")
        denominator = self.g * unit_x + self.h * unit_y + 1
        if not isfinite(denominator) or abs(denominator) <= 1e-12:
            raise ValueError("projective point maps to infinity")
        point = Point(
            (self.a * unit_x + self.b * unit_y + self.c) / denominator,
            (self.d * unit_x + self.e * unit_y + self.f) / denominator,
        )
        if not point.is_finite:
            raise ValueError("projective point is not finite")
        return point


@dataclass(frozen=True, slots=True)
class BoardGeometry:
    quad: Quad
    orientation: BoardOrientation = BoardOrientation.WHITE_BOTTOM
    _transform: _ProjectiveTransform | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.quad, Quad):
            raise TypeError("quad must be a Quad")
        try:
            orientation = BoardOrientation(self.orientation)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"unsupported board orientation: {self.orientation!r}"
            ) from error
        object.__setattr__(self, "orientation", orientation)
        object.__setattr__(
            self, "_transform", _ProjectiveTransform.from_quad(self.quad)
        )

    def point(self, unit_x: float, unit_y: float) -> Point:
        if not 0 <= unit_x <= 1 or not 0 <= unit_y <= 1:
            raise ValueError("unit coordinates must be within the board")
        assert self._transform is not None
        return self._transform.map(unit_x, unit_y)

    def grid_intersection(self, column: int, row: int) -> Point:
        if not 0 <= column <= 8 or not 0 <= row <= 8:
            raise ValueError("grid indices must be within 0...8")
        return self.point(column / 8, row / 8)

    def center_of(self, square: ChessSquare) -> Point:
        unit_x = (square.file + 0.5) / 8
        unit_y = (8 - square.rank + 0.5) / 8
        if self.orientation is BoardOrientation.BLACK_BOTTOM:
            unit_x = 1 - unit_x
            unit_y = 1 - unit_y
        return self.point(unit_x, unit_y)

    def corners_of(self, square: ChessSquare) -> Quad:
        minimum_x = square.file / 8
        maximum_x = (square.file + 1) / 8
        minimum_y = (8 - square.rank) / 8
        maximum_y = (9 - square.rank) / 8
        if self.orientation is BoardOrientation.BLACK_BOTTOM:
            minimum_x, maximum_x = 1 - maximum_x, 1 - minimum_x
            minimum_y, maximum_y = 1 - maximum_y, 1 - minimum_y
        return Quad(
            self.point(minimum_x, minimum_y),
            self.point(maximum_x, minimum_y),
            self.point(maximum_x, maximum_y),
            self.point(minimum_x, maximum_y),
        )

    def contains(self, point: Point) -> bool:
        return self.quad.contains(point)


@dataclass(frozen=True, slots=True)
class BoardDetection:
    geometry: BoardGeometry
    confidence: float
    proposal_score: float
    captured_at: datetime | float = field(default_factory=lambda: datetime.now(UTC))
    source_window_id: int | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be finite and within 0...1")
        if not isfinite(self.proposal_score) or not 0 <= self.proposal_score <= 1:
            raise ValueError("proposal score must be finite and within 0...1")
        if self.source_window_id is not None and (
            isinstance(self.source_window_id, bool)
            or not isinstance(self.source_window_id, int)
            or self.source_window_id < 0
        ):
            raise ValueError("source window ID must be a non-negative integer")
