# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Passive perspective-correct Chess board overlay."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Protocol

from voice_chess_cua.domain.chess import ChessSquare
from voice_chess_cua.domain.geometry import (
    BoardDetection,
    BoardGeometry,
    Point,
    Quad,
    Rect,
)
from voice_chess_cua.hud import HUDPhase, HUDPresentation, HUDState, present_hud

from ._main_thread import run_on_main

_APPKIT_OVERLAY_CLASSES: tuple[Any, Any] | None = None
_HUD_VOICE_VALUE_WIDTH = 106.0
_HUD_WAVEFORM_FRAME = Rect(186.0, 119.0, 86.0, 14.0)
_HUD_WAVEFORM_LINE_WIDTH = 1.5
_HUD_ROWS = (
    ("VOICE", 116.0),
    ("TURN", 84.0),
    ("HEARD", 36.0),
)


@dataclass(frozen=True, slots=True)
class OverlayStyle:
    grid_line_width: float = 1.2
    grid_shadow_alpha: float = 0.7
    grid_shadow_radius: float = 1.5
    highlight_line_width: float = 3.0
    source_fill_alpha: float = 0.20
    destination_fill_alpha: float = 0.22
    label_font_size: float = 9.0
    label_background_alpha: float = 0.82
    label_corner_radius: float = 5.0
    label_width: float = 22.0
    label_height: float = 14.0
    hud_width: float = 286.0
    hud_height: float = 154.0
    hud_gap: float = 14.0
    hud_margin: float = 12.0
    hud_corner_radius: float = 14.0
    hud_background_alpha: float = 0.86


@dataclass(frozen=True, slots=True)
class OverlaySegment:
    start: Point
    end: Point


@dataclass(frozen=True, slots=True)
class OverlayLabel:
    text: str
    center: Point


@dataclass(frozen=True, slots=True)
class OverlayModel:
    grid_segments: tuple[OverlaySegment, ...]
    labels: tuple[OverlayLabel, ...]
    source_quad: Quad | None
    destination_quad: Quad | None


@dataclass(frozen=True, slots=True)
class HUDLayout:
    frame: Rect
    overlaps_board: bool


def place_hud(
    board: Quad,
    visible_frame: Rect,
    *,
    width: float = 286.0,
    height: float = 154.0,
    gap: float = 14.0,
    margin: float = 12.0,
) -> HUDLayout:
    board_frame = _quad_bounds(board)
    usable = Rect(
        visible_frame.x + margin,
        visible_frame.y + margin,
        max(1.0, visible_frame.width - 2 * margin),
        max(1.0, visible_frame.height - 2 * margin),
    )
    candidates = (
        Rect(board_frame.max_x + gap, board_frame.center.y - height / 2, width, height),
        Rect(
            board_frame.min_x - gap - width,
            board_frame.center.y - height / 2,
            width,
            height,
        ),
        Rect(
            board_frame.center.x - width / 2,
            board_frame.min_y - gap - height,
            width,
            height,
        ),
        Rect(board_frame.center.x - width / 2, board_frame.max_y + gap, width, height),
    )
    for candidate in candidates:
        if _rect_contains(usable, candidate) and not _rects_overlap(
            candidate, board_frame
        ):
            return HUDLayout(candidate, overlaps_board=False)

    compact_width = min(width, usable.width)
    compact_height = min(height, usable.height)
    inset = Rect(
        min(
            max(board_frame.max_x - compact_width, usable.min_x),
            usable.max_x - compact_width,
        ),
        min(max(board_frame.min_y, usable.min_y), usable.max_y - compact_height),
        compact_width,
        compact_height,
    )
    return HUDLayout(inset, overlaps_board=_rects_overlap(inset, board_frame))


def build_waveform_segments(
    waveform: tuple[float, ...],
    frame: Rect,
    *,
    line_width: float = _HUD_WAVEFORM_LINE_WIDTH,
) -> tuple[OverlaySegment, ...]:
    """Map ordered amplitudes to bounded, center-aligned vertical segments."""

    if not isfinite(line_width) or line_width <= 0:
        raise ValueError("waveform line width must be finite and positive")
    if line_width > min(frame.width, frame.height):
        raise ValueError("waveform line width must fit inside its frame")

    inset = line_width / 2
    left = frame.min_x + inset
    right = frame.max_x - inset
    center_y = frame.center.y
    maximum_half_height = frame.height / 2 - inset
    amplitudes: list[float] = []
    for sample in waveform:
        value = float(sample)
        amplitudes.append(min(abs(value), 1.0) if isfinite(value) else 0.0)
    if not amplitudes or not any(amplitudes):
        return (OverlaySegment(Point(left, center_y), Point(right, center_y)),)

    x_step = (right - left) / max(1, len(amplitudes) - 1)
    return tuple(
        OverlaySegment(
            Point(
                frame.center.x if len(amplitudes) == 1 else left + index * x_step,
                center_y - sqrt(amplitude) * maximum_half_height,
            ),
            Point(
                frame.center.x if len(amplitudes) == 1 else left + index * x_step,
                center_y + sqrt(amplitude) * maximum_half_height,
            ),
        )
        for index, amplitude in enumerate(amplitudes)
    )


def build_overlay_model(
    geometry: BoardGeometry,
    source: ChessSquare | None = None,
    destination: ChessSquare | None = None,
) -> OverlayModel:
    segments: list[OverlaySegment] = []
    for index in range(9):
        segments.append(
            OverlaySegment(
                geometry.grid_intersection(index, 0),
                geometry.grid_intersection(index, 8),
            )
        )
        segments.append(
            OverlaySegment(
                geometry.grid_intersection(0, index),
                geometry.grid_intersection(8, index),
            )
        )
    return OverlayModel(
        grid_segments=tuple(segments),
        labels=tuple(
            OverlayLabel(square.notation, geometry.center_of(square))
            for square in ChessSquare.all()
        ),
        source_quad=None if source is None else geometry.corners_of(source),
        destination_quad=(
            None if destination is None else geometry.corners_of(destination)
        ),
    )


class OverlayBackend(Protocol):
    async def show(
        self,
        detection: BoardDetection,
        source: ChessSquare | None,
        destination: ChessSquare | None,
    ) -> bool: ...

    async def update_hud(self, presentation: HUDPresentation) -> None: ...

    async def clear_board(self) -> None: ...

    async def hide(self) -> None: ...

    async def destroy(self) -> None: ...


class BoardOverlay:
    """Runtime-facing overlay that accepts stable detections only."""

    def __init__(self, backend: OverlayBackend | None = None) -> None:
        self._backend = backend
        self._visible_window_id: int | None = None
        self._hud = present_hud(HUDState())

    @property
    def backend(self) -> OverlayBackend:
        if self._backend is None:
            self._backend = _AppKitOverlayBackend()
        return self._backend

    @property
    def visible_window_id(self) -> int | None:
        return self._visible_window_id

    async def show_stable(
        self,
        detection: object,
        source: ChessSquare | None = None,
        destination: ChessSquare | None = None,
    ) -> bool:
        if not isinstance(detection, BoardDetection):
            raise TypeError("stable overlay updates require a BoardDetection")
        if detection.source_window_id is None:
            await self.clear_board()
            return False
        backend = self.backend
        await backend.update_hud(self._hud)
        presented = await backend.show(detection, source, destination)
        self._visible_window_id = (
            detection.source_window_id if presented is not False else None
        )
        return presented is not False

    async def update_hud(self, state: object) -> None:
        if not isinstance(state, HUDPresentation):
            raise TypeError("HUD updates require a HUDPresentation")
        if state.revision < self._hud.revision:
            return
        self._hud = state
        await self.backend.update_hud(state)

    async def clear_board(self) -> None:
        if self._backend is not None:
            await self._backend.clear_board()
        self._visible_window_id = None

    async def hide(self) -> None:
        if self._backend is not None:
            await self._backend.hide()
        self._visible_window_id = None

    async def destroy(self) -> None:
        if self._backend is not None:
            await self._backend.destroy()
        self._visible_window_id = None
        self._hud = present_hud(HUDState())


class _AppKitOverlayBackend:
    def __init__(self) -> None:
        from ._native import load_framework

        self._appkit = load_framework("AppKit")
        self._quartz = load_framework("Quartz")
        self._style = OverlayStyle()
        self._hud = present_hud(HUDState())
        self._panel: Any | None = None
        self._view: Any | None = None
        self._screen_frame: Rect | None = None
        self._panel_class: Any | None = None
        self._view_class: Any | None = None
        self._hud_frame: Rect | None = None

    async def show(
        self,
        detection: BoardDetection,
        source: ChessSquare | None,
        destination: ChessSquare | None,
    ) -> bool:
        return await run_on_main(lambda: self._show(detection, source, destination))

    async def update_hud(self, presentation: HUDPresentation) -> None:
        if presentation.revision < self._hud.revision:
            return
        self._hud = presentation
        await run_on_main(lambda: self._update_hud(presentation))

    async def clear_board(self) -> None:
        await run_on_main(self._clear_board)

    async def hide(self) -> None:
        await run_on_main(self._hide)

    async def destroy(self) -> None:
        await run_on_main(self._destroy)

    def _make_classes(self) -> None:
        global _APPKIT_OVERLAY_CLASSES
        if _APPKIT_OVERLAY_CLASSES is not None:
            self._panel_class, self._view_class = _APPKIT_OVERLAY_CLASSES
            return
        import objc  # type: ignore[import-untyped]

        appkit = self._appkit
        quartz = self._quartz
        style = self._style

        panel_base: Any = appkit.NSPanel
        view_base: Any = appkit.NSView

        class PassivePanel(panel_base):  # type: ignore[misc]
            def canBecomeKey(self) -> bool:
                return False

            def canBecomeMain(self) -> bool:
                return False

        class BoardOverlayView(view_base):  # type: ignore[misc]
            _grid: Any
            _source: Any
            _destination: Any
            _labels: list[Any]
            _hud_card: Any
            _hud_values: dict[str, Any]
            _waveform: Any

            def initWithFrame_(self, frame: object) -> object:
                view = objc.super(BoardOverlayView, self).initWithFrame_(frame)
                if view is None:
                    return None
                view.setWantsLayer_(True)
                view.layer().setBackgroundColor_(appkit.NSColor.clearColor().CGColor())
                view._grid = quartz.CAShapeLayer.layer()
                view._source = quartz.CAShapeLayer.layer()
                view._destination = quartz.CAShapeLayer.layer()
                view._labels = []
                view._hud_values = {}
                view._configure_shape(
                    view._grid, appkit.NSColor.whiteColor(), style.grid_line_width
                )
                view._grid.setShadowColor_(appkit.NSColor.blackColor().CGColor())
                view._grid.setShadowOpacity_(style.grid_shadow_alpha)
                view._grid.setShadowRadius_(style.grid_shadow_radius)
                view._grid.setShadowOffset_((0.0, 0.0))
                view._configure_shape(
                    view._source,
                    appkit.NSColor.systemCyanColor(),
                    style.highlight_line_width,
                )
                view._source.setFillColor_(
                    appkit.NSColor.systemCyanColor()
                    .colorWithAlphaComponent_(style.source_fill_alpha)
                    .CGColor()
                )
                view._configure_shape(
                    view._destination,
                    appkit.NSColor.systemOrangeColor(),
                    style.highlight_line_width,
                )
                view._destination.setFillColor_(
                    appkit.NSColor.systemOrangeColor()
                    .colorWithAlphaComponent_(style.destination_fill_alpha)
                    .CGColor()
                )
                view._hud_card = view._make_hud_card()
                view.addSubview_(view._hud_card)
                return view

            def isFlipped(self) -> bool:
                return True

            def _configure_shape(self, layer: Any, color: Any, width: float) -> None:
                layer.setStrokeColor_(color.CGColor())
                layer.setFillColor_(appkit.NSColor.clearColor().CGColor())
                layer.setLineWidth_(width)
                layer.setLineJoin_(quartz.kCALineJoinRound)
                layer.setLineCap_(quartz.kCALineCapRound)
                self.layer().addSublayer_(layer)

            def _make_hud_card(self) -> Any:
                card = appkit.NSView.alloc().initWithFrame_(
                    ((0.0, 0.0), (style.hud_width, style.hud_height))
                )
                card.setWantsLayer_(True)
                card.layer().setBackgroundColor_(
                    appkit.NSColor.blackColor()
                    .colorWithAlphaComponent_(style.hud_background_alpha)
                    .CGColor()
                )
                card.layer().setCornerRadius_(style.hud_corner_radius)
                card.layer().setBorderWidth_(1.0)
                card.layer().setBorderColor_(
                    appkit.NSColor.whiteColor().colorWithAlphaComponent_(0.18).CGColor()
                )
                self._waveform = quartz.CAShapeLayer.layer()
                self._waveform.setFrame_(
                    ((0.0, 0.0), (style.hud_width, style.hud_height))
                )
                self._waveform.setStrokeColor_(
                    appkit.NSColor.systemGreenColor().CGColor()
                )
                self._waveform.setFillColor_(appkit.NSColor.clearColor().CGColor())
                self._waveform.setLineWidth_(_HUD_WAVEFORM_LINE_WIDTH)
                self._waveform.setLineJoin_(quartz.kCALineJoinRound)
                self._waveform.setLineCap_(quartz.kCALineCapRound)
                card.layer().addSublayer_(self._waveform)
                rows = _HUD_ROWS
                label_font = appkit.NSFont.fontWithName_size_(
                    "Avenir Next Demi Bold", 10.0
                )
                if label_font is None:
                    label_font = appkit.NSFont.systemFontOfSize_weight_(
                        10.0, appkit.NSFontWeightSemibold
                    )
                value_font = appkit.NSFont.fontWithName_size_(
                    "Avenir Next Medium", 12.0
                )
                if value_font is None:
                    value_font = appkit.NSFont.systemFontOfSize_weight_(
                        12.0, appkit.NSFontWeightMedium
                    )
                for name, y in rows:
                    label = appkit.NSTextField.labelWithString_(name)
                    label.setFont_(label_font)
                    label.setTextColor_(
                        appkit.NSColor.whiteColor().colorWithAlphaComponent_(0.52)
                    )
                    label.setFrame_(((14.0, y), (52.0, 20.0)))
                    card.addSubview_(label)
                    value = appkit.NSTextField.labelWithString_("-")
                    value.setFont_(value_font)
                    value.setTextColor_(appkit.NSColor.whiteColor())
                    value.setLineBreakMode_(appkit.NSLineBreakByTruncatingTail)
                    value.setMaximumNumberOfLines_(2 if name == "HEARD" else 1)
                    value_width = _HUD_VOICE_VALUE_WIDTH if name == "VOICE" else 202.0
                    value.setFrame_(
                        ((70.0, y), (value_width, 28.0 if name == "HEARD" else 20.0))
                    )
                    card.addSubview_(value)
                    self._hud_values[name] = value
                return card

            def updateHUDPresentation_frame_(
                self, presentation: HUDPresentation, frame: Rect
            ) -> None:
                self._hud_card.setFrame_(
                    ((frame.x, frame.y), (frame.width, frame.height))
                )
                values = {
                    "VOICE": presentation.voice,
                    "TURN": presentation.turn,
                    "HEARD": presentation.heard,
                }
                for name, value in values.items():
                    self._hud_values[name].setStringValue_(value)
                voice_color = appkit.NSColor.systemGreenColor()
                if presentation.is_error:
                    voice_color = appkit.NSColor.systemRedColor()
                elif presentation.voice == HUDPhase.PAUSED.value:
                    voice_color = appkit.NSColor.systemOrangeColor()
                elif presentation.is_busy:
                    voice_color = appkit.NSColor.systemCyanColor()
                self._hud_values["VOICE"].setTextColor_(voice_color)
                self._waveform.setStrokeColor_(voice_color.CGColor())
                self._waveform.setPath_(
                    _segments_path(
                        quartz,
                        build_waveform_segments(
                            presentation.waveform,
                            _HUD_WAVEFORM_FRAME,
                            line_width=_HUD_WAVEFORM_LINE_WIDTH,
                        ),
                    )
                )
                self._hud_card.setHidden_(False)

            def updateModel_(self, model: OverlayModel) -> None:
                self._grid.setPath_(_segments_path(quartz, model.grid_segments))
                self._source.setPath_(_quad_path(quartz, model.source_quad))
                self._destination.setPath_(_quad_path(quartz, model.destination_quad))
                for label in self._labels:
                    label.removeFromSuperview()
                self._labels = []
                for value in model.labels:
                    label = appkit.NSTextField.labelWithString_(value.text)
                    label.setFont_(
                        appkit.NSFont.monospacedSystemFontOfSize_weight_(
                            style.label_font_size,
                            appkit.NSFontWeightSemibold,
                        )
                    )
                    label.setTextColor_(appkit.NSColor.whiteColor())
                    label.setAlignment_(appkit.NSTextAlignmentCenter)
                    label.setBackgroundColor_(
                        appkit.NSColor.blackColor().colorWithAlphaComponent_(
                            style.label_background_alpha
                        )
                    )
                    label.setDrawsBackground_(True)
                    label.setWantsLayer_(True)
                    label.layer().setCornerRadius_(style.label_corner_radius)
                    label.layer().setMasksToBounds_(True)
                    label.setFrame_(
                        self._frame(
                            value.center.x - style.label_width / 2,
                            value.center.y - style.label_height / 2,
                            style.label_width,
                            style.label_height,
                        )
                    )
                    self.addSubview_(label)
                    self._labels.append(label)

            def clearBoard(self) -> None:
                self._grid.setPath_(None)
                self._source.setPath_(None)
                self._destination.setPath_(None)
                for label in self._labels:
                    label.removeFromSuperview()
                self._labels = []

            def clear(self) -> None:
                self.clearBoard()
                self._hud_card.setHidden_(True)

            @staticmethod
            def _frame(x: float, y: float, width: float, height: float) -> object:
                return ((x, y), (width, height))

        _APPKIT_OVERLAY_CLASSES = (PassivePanel, BoardOverlayView)
        self._panel_class, self._view_class = _APPKIT_OVERLAY_CLASSES

    def _show(
        self,
        detection: BoardDetection,
        source: ChessSquare | None,
        destination: ChessSquare | None,
    ) -> bool:
        if self._panel_class is None or self._view_class is None:
            self._make_classes()
        screen, primary_max_y = self._screen_for(detection.geometry.quad.center)
        if screen is None:
            self._hide()
            return False
        frame = _native_rect(screen.frame())
        local_geometry = _local_geometry(detection.geometry, frame, primary_max_y)
        visible_frame = _local_visible_frame(screen, frame)
        layout = place_hud(
            local_geometry.quad,
            visible_frame,
            width=self._style.hud_width,
            height=self._style.hud_height,
            gap=self._style.hud_gap,
            margin=self._style.hud_margin,
        )
        self._hud_frame = layout.frame
        self._ensure_panel(screen, frame)
        view = self._view
        panel = self._panel
        assert view is not None
        assert panel is not None
        view.updateModel_(build_overlay_model(local_geometry, source, destination))
        view.updateHUDPresentation_frame_(self._hud, layout.frame)
        panel.orderFrontRegardless()
        return True

    def _ensure_panel(self, screen: Any, frame: Rect) -> None:
        native_frame = screen.frame()
        if self._panel is not None and self._view is not None:
            if frame != self._screen_frame:
                self._panel.setFrame_display_(native_frame, True)
                self._view.setFrame_(((0.0, 0.0), (frame.width, frame.height)))
                self._screen_frame = frame
            return
        mask = (
            self._appkit.NSWindowStyleMaskBorderless
            | self._appkit.NSWindowStyleMaskNonactivatingPanel
        )
        assert self._panel_class is not None
        assert self._view_class is not None
        panel = self._panel_class.alloc().initWithContentRect_styleMask_backing_defer_(
            native_frame,
            mask,
            self._appkit.NSBackingStoreBuffered,
            False,
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(self._appkit.NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setFloatingPanel_(True)
        panel.setLevel_(self._appkit.NSFloatingWindowLevel)
        panel.setCollectionBehavior_(
            self._appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | self._appkit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | self._appkit.NSWindowCollectionBehaviorIgnoresCycle
        )
        view = self._view_class.alloc().initWithFrame_(
            ((0.0, 0.0), (frame.width, frame.height))
        )
        panel.setContentView_(view)
        self._panel = panel
        self._view = view
        self._screen_frame = frame

    def _screen_for(self, center: Point) -> tuple[Any | None, float]:
        screens = tuple(self._appkit.NSScreen.screens())
        primary = next(
            (
                screen
                for screen in screens
                if float(screen.frame().origin.x) == 0
                and float(screen.frame().origin.y) == 0
            ),
            self._appkit.NSScreen.mainScreen(),
        )
        if primary is None:
            return None, 0.0
        primary_max_y = float(primary.frame().origin.y + primary.frame().size.height)
        appkit_center = Point(center.x, primary_max_y - center.y)
        for screen in screens:
            frame = _native_rect(screen.frame())
            if frame.contains(appkit_center):
                return screen, primary_max_y
        return None, primary_max_y

    def _update_hud(self, presentation: HUDPresentation) -> None:
        if self._view is None or self._hud_frame is None:
            screen = self._default_screen()
            if screen is None:
                raise RuntimeError("No display is available for the Voice Chess HUD.")
            if self._panel_class is None or self._view_class is None:
                self._make_classes()
            frame = _native_rect(screen.frame())
            visible_frame = _local_visible_frame(screen, frame)
            self._hud_frame = _standalone_hud_frame(
                visible_frame,
                width=self._style.hud_width,
                height=self._style.hud_height,
                margin=self._style.hud_margin,
            )
            self._ensure_panel(screen, frame)
            assert self._view is not None
            self._view.clearBoard()
        assert self._view is not None
        assert self._panel is not None
        assert self._hud_frame is not None
        self._view.updateHUDPresentation_frame_(presentation, self._hud_frame)
        self._panel.orderFrontRegardless()

    def _default_screen(self) -> Any | None:
        main = self._appkit.NSScreen.mainScreen()
        if main is not None:
            return main
        screens = tuple(self._appkit.NSScreen.screens())
        return screens[0] if screens else None

    def _clear_board(self) -> None:
        if self._view is not None:
            self._view.clearBoard()

    def _hide(self) -> None:
        if self._view is not None:
            self._view.clear()
        if self._panel is not None:
            self._panel.orderOut_(None)

    def _destroy(self) -> None:
        self._hide()
        self._hud = present_hud(HUDState())
        if self._panel is not None:
            self._panel.close()
        self._panel = None
        self._view = None
        self._screen_frame = None
        self._hud_frame = None


def _segments_path(quartz: Any, segments: tuple[OverlaySegment, ...]) -> object:
    path = quartz.CGPathCreateMutable()
    for segment in segments:
        quartz.CGPathMoveToPoint(path, None, segment.start.x, segment.start.y)
        quartz.CGPathAddLineToPoint(path, None, segment.end.x, segment.end.y)
    return path


def _quad_path(quartz: Any, quad: Quad | None) -> Any:
    if quad is None:
        return None
    path = quartz.CGPathCreateMutable()
    quartz.CGPathMoveToPoint(path, None, quad.top_left.x, quad.top_left.y)
    for point in (quad.top_right, quad.bottom_right, quad.bottom_left):
        quartz.CGPathAddLineToPoint(path, None, point.x, point.y)
    quartz.CGPathCloseSubpath(path)
    return path


def _quad_bounds(quad: Quad) -> Rect:
    xs = tuple(point.x for point in quad.points)
    ys = tuple(point.y for point in quad.points)
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _rect_contains(container: Rect, candidate: Rect) -> bool:
    return (
        container.min_x <= candidate.min_x
        and candidate.max_x <= container.max_x
        and container.min_y <= candidate.min_y
        and candidate.max_y <= container.max_y
    )


def _rects_overlap(left: Rect, right: Rect) -> bool:
    return not (
        left.max_x <= right.min_x
        or right.max_x <= left.min_x
        or left.max_y <= right.min_y
        or right.max_y <= left.min_y
    )


def _standalone_hud_frame(
    visible_frame: Rect,
    *,
    width: float,
    height: float,
    margin: float,
) -> Rect:
    compact_width = min(width, visible_frame.width)
    compact_height = min(height, visible_frame.height)
    return Rect(
        min(
            max(visible_frame.max_x - compact_width - margin, visible_frame.min_x),
            visible_frame.max_x - compact_width,
        ),
        min(
            max(visible_frame.min_y + margin, visible_frame.min_y),
            visible_frame.max_y - compact_height,
        ),
        compact_width,
        compact_height,
    )


def _local_visible_frame(screen: Any, overlay_frame: Rect) -> Rect:
    visible = _native_rect(screen.visibleFrame())
    return Rect(
        visible.x - overlay_frame.x,
        overlay_frame.height - (visible.y - overlay_frame.y) - visible.height,
        visible.width,
        visible.height,
    )


def _native_rect(rect: object) -> Rect:
    return Rect(
        float(rect.origin.x),  # type: ignore[attr-defined]
        float(rect.origin.y),  # type: ignore[attr-defined]
        float(rect.size.width),  # type: ignore[attr-defined]
        float(rect.size.height),  # type: ignore[attr-defined]
    )


def _local_geometry(
    geometry: BoardGeometry,
    overlay_frame: Rect,
    primary_screen_max_y: float,
) -> BoardGeometry:
    def local(point: Point) -> Point:
        appkit_y = primary_screen_max_y - point.y
        local_bottom_y = appkit_y - overlay_frame.y
        return Point(
            point.x - overlay_frame.x,
            overlay_frame.height - local_bottom_y,
        )

    return BoardGeometry(
        Quad(*(local(point) for point in geometry.quad.points)),
        geometry.orientation,
    )
