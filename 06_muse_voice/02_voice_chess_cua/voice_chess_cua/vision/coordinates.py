# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Conversions between capture pixels, global CG coordinates, and AppKit overlays."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from voice_chess_cua.domain.geometry import PixelSize, Point, Rect


@dataclass(frozen=True, slots=True)
class ScreenCoordinateMapper:
    captured_image_size: PixelSize
    captured_global_frame: Rect
    primary_screen_max_y: float

    def __post_init__(self) -> None:
        if not isfinite(self.primary_screen_max_y):
            raise ValueError("primary screen maximum y must be finite")

    @property
    def pixels_per_point_x(self) -> float:
        return self.captured_image_size.width / self.captured_global_frame.width

    @property
    def pixels_per_point_y(self) -> float:
        return self.captured_image_size.height / self.captured_global_frame.height

    def global_cg_from_captured(self, point: Point) -> Point:
        if not point.is_finite or not (
            0 <= point.x <= self.captured_image_size.width
            and 0 <= point.y <= self.captured_image_size.height
        ):
            raise ValueError("captured point lies outside the image")
        return Point(
            self.captured_global_frame.x + point.x / self.pixels_per_point_x,
            self.captured_global_frame.y + point.y / self.pixels_per_point_y,
        )

    def captured_from_global_cg(self, point: Point) -> Point:
        if not self.captured_global_frame.contains(point):
            raise ValueError("global point lies outside the captured frame")
        return Point(
            (point.x - self.captured_global_frame.x) * self.pixels_per_point_x,
            (point.y - self.captured_global_frame.y) * self.pixels_per_point_y,
        )

    def appkit_global_from_global_cg(self, point: Point) -> Point:
        if not point.is_finite:
            raise ValueError("global point must be finite")
        converted = Point(point.x, self.primary_screen_max_y - point.y)
        if not converted.is_finite:
            raise ValueError("converted AppKit point must be finite")
        return converted

    def global_cg_from_appkit_global(self, point: Point) -> Point:
        if not point.is_finite:
            raise ValueError("AppKit point must be finite")
        converted = Point(point.x, self.primary_screen_max_y - point.y)
        if not converted.is_finite:
            raise ValueError("converted global point must be finite")
        return converted

    def overlay_local_from_global_cg(self, point: Point, overlay_frame: Rect) -> Point:
        appkit_point = self.appkit_global_from_global_cg(point)
        return Point(
            appkit_point.x - overlay_frame.min_x,
            appkit_point.y - overlay_frame.min_y,
        )

    def overlay_local_top_left_from_global_cg(
        self,
        point: Point,
        overlay_frame: Rect,
    ) -> Point:
        local = self.overlay_local_from_global_cg(point, overlay_frame)
        return Point(local.x, overlay_frame.height - local.y)

    def appkit_global_rect_from_global_cg(self, rect: Rect) -> Rect:
        return Rect(
            rect.x,
            self.primary_screen_max_y - rect.max_y,
            rect.width,
            rect.height,
        )
