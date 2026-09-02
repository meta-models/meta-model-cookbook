# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
import builtins
import importlib
import sys
import threading
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest

from voice_chess_cua.domain.chess import ChessSquare
from voice_chess_cua.domain.geometry import (
    BoardDetection,
    BoardGeometry,
    Point,
    Quad,
    Rect,
)
from voice_chess_cua.hud import HUDPhase, HUDState, HUDUpdate, present_hud, reduce_hud
from voice_chess_cua.macos.audio import AudioBufferOverrunError, AudioCaptureService
from voice_chess_cua.macos.overlay import (
    BoardOverlay,
    OverlayStyle,
    build_overlay_model,
    build_waveform_segments,
    place_hud,
)
from voice_chess_cua.voice.pcm import (
    BYTES_PER_CHUNK,
    FRAMES_PER_CHUNK,
    float_samples_to_pcm16le,
    resample_linear,
)


def perspective_geometry() -> BoardGeometry:
    return BoardGeometry(
        Quad(
            Point(263, 198),
            Point(714, 198),
            Point(777, 650),
            Point(201, 650),
        )
    )


def test_aim_point_moves_towards_the_far_edge_and_stays_inside_the_square() -> None:
    geometry = perspective_geometry()
    square = ChessSquare.parse("E2")
    corners = geometry.corners_of(square)

    centre = geometry.aim_point(square)
    shallow = geometry.aim_point(square, 0.34)

    assert centre == geometry.center_of(square)
    assert corners.top_left.y < shallow.y < centre.y < corners.bottom_left.y
    assert corners.contains(shallow)
    assert geometry.contains(shallow)


@pytest.mark.parametrize("depth", [0.0, 1.0, -0.1, 1.5])
def test_aim_point_rejects_a_depth_outside_the_square(depth: float) -> None:
    with pytest.raises(ValueError, match="aim depth"):
        perspective_geometry().aim_point(ChessSquare.parse("E2"), depth)


def test_overlay_model_has_exact_perspective_grid_labels_and_highlights() -> None:
    geometry = perspective_geometry()
    source = ChessSquare.parse("A1")
    destination = ChessSquare.parse("H8")

    model = build_overlay_model(geometry, source, destination)

    assert len(model.grid_segments) == 18
    assert model.grid_segments[0].start == geometry.grid_intersection(0, 0)
    assert model.grid_segments[0].end == geometry.grid_intersection(0, 8)
    assert model.grid_segments[-1].start == geometry.grid_intersection(0, 8)
    assert model.grid_segments[-1].end == geometry.grid_intersection(8, 8)
    assert len(model.labels) == 64
    assert [label.text for label in model.labels[:8]] == [
        "A1",
        "B1",
        "C1",
        "D1",
        "E1",
        "F1",
        "G1",
        "H1",
    ]
    assert model.labels[0].center == geometry.center_of(source)
    assert model.labels[-1].center == geometry.center_of(destination)
    assert model.source_quad == geometry.corners_of(source)
    assert model.destination_quad == geometry.corners_of(destination)


def test_overlay_style_matches_legacy_visual_contract() -> None:
    style = OverlayStyle()

    assert style.grid_line_width == 1.2
    assert style.grid_shadow_alpha == 0.7
    assert style.grid_shadow_radius == 1.5
    assert style.highlight_line_width == 3
    assert style.source_fill_alpha == 0.20
    assert style.destination_fill_alpha == 0.22
    assert style.label_font_size == 9
    assert style.label_background_alpha == 0.82
    assert style.label_corner_radius == 5
    assert (style.label_width, style.label_height) == (22, 14)


def test_waveform_geometry_orders_samples_and_applies_sqrt_scaling() -> None:
    frame = Rect(10.0, 20.0, 100.0, 20.0)

    segments = build_waveform_segments((0.25, 1.0), frame, line_width=2.0)

    assert segments == (
        type(segments[0])(Point(11.0, 25.5), Point(11.0, 34.5)),
        type(segments[0])(Point(109.0, 21.0), Point(109.0, 39.0)),
    )
    assert segments[0].start.x < segments[-1].start.x
    assert segments[0].end.y - segments[0].start.y == pytest.approx(
        (segments[1].end.y - segments[1].start.y) / 2
    )


def test_waveform_geometry_keeps_silence_and_extremes_inside_frame() -> None:
    frame = Rect(3.0, 7.0, 40.0, 12.0)

    silence = build_waveform_segments((0.0, 0.0, 0.0), frame, line_width=2.0)
    segments = build_waveform_segments(
        (-4.0, float("inf"), 0.01), frame, line_width=2.0
    )

    assert silence == (type(silence[0])(Point(4.0, 13.0), Point(42.0, 13.0)),)
    assert all(
        frame.contains(point)
        for segment in segments
        for point in (segment.start, segment.end)
    )
    assert segments[0].start.y == 8.0
    assert segments[0].end.y == 18.0
    assert segments[1].start == segments[1].end == Point(23.0, 13.0)
    assert segments[2].start.y < frame.center.y < segments[2].end.y

    single = build_waveform_segments((1.0,), frame, line_width=2.0)
    assert single[0].start.x == single[0].end.x == frame.center.x


class OverlayBackend:
    def __init__(self) -> None:
        self.shown: list[int] = []
        self.hide_count = 0
        self.clear_board_count = 0
        self.destroy_count = 0
        self.hud = []

    async def show(self, detection, source, destination) -> bool:
        del source, destination
        self.shown.append(detection.source_window_id)
        return True

    async def update_hud(self, presentation) -> None:
        self.hud.append(presentation)

    async def clear_board(self) -> None:
        self.clear_board_count += 1

    async def hide(self) -> None:
        self.hide_count += 1

    async def destroy(self) -> None:
        self.destroy_count += 1


async def test_first_hud_update_constructs_backend_before_board_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import voice_chess_cua.macos.overlay as overlay_module

    backend = OverlayBackend()
    monkeypatch.setattr(overlay_module, "_AppKitOverlayBackend", lambda: backend)
    overlay = BoardOverlay()
    presentation = present_hud(
        reduce_hud(HUDState(), HUDUpdate(phase=HUDPhase.LISTENING))
    )

    await overlay.update_hud(presentation)

    assert overlay.backend is backend
    assert backend.hud == [presentation]
    assert backend.shown == []


async def test_unbound_detection_clears_board_without_hiding_hud() -> None:
    backend = OverlayBackend()
    overlay = BoardOverlay(backend)
    unbound = BoardDetection
    unbound = BoardDetection(perspective_geometry(), 0.99)
    bound = BoardDetection(perspective_geometry(), 0.99, source_window_id=17)

    assert await overlay.show_stable(unbound) is False
    assert await overlay.show_stable(bound) is True
    assert overlay.visible_window_id == 17
    await overlay.hide()
    await overlay.destroy()

    assert backend.shown == [17]
    assert backend.hud[-1].voice == "Starting"
    assert backend.clear_board_count == 1
    assert backend.hide_count == 1
    assert backend.destroy_count == 1
    assert overlay.visible_window_id is None


async def test_overlay_does_not_report_visibility_when_presentation_fails() -> None:
    backend = OverlayBackend()

    async def fail_to_present(detection, source, destination) -> bool:
        del detection, source, destination
        return False

    backend.show = fail_to_present
    overlay = BoardOverlay(backend)
    detection = BoardDetection(perspective_geometry(), 0.99, source_window_id=17)

    assert await overlay.show_stable(detection) is False

    assert overlay.visible_window_id is None


def test_appkit_view_updates_persistent_waveform_without_touching_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeColor:
        def __init__(self, name: str) -> None:
            self.name = name

        def CGColor(self) -> str:
            return self.name

    class FakeColors:
        @staticmethod
        def systemGreenColor() -> FakeColor:
            return FakeColor("green")

        @staticmethod
        def systemRedColor() -> FakeColor:
            return FakeColor("red")

        @staticmethod
        def systemOrangeColor() -> FakeColor:
            return FakeColor("orange")

        @staticmethod
        def systemCyanColor() -> FakeColor:
            return FakeColor("cyan")

    class FakeLayer:
        def __init__(self) -> None:
            self.path: object | None = None
            self.stroke_color: object | None = None

        def setPath_(self, path: object | None) -> None:
            self.path = path

        def setStrokeColor_(self, color: object) -> None:
            self.stroke_color = color

    class FakeCard:
        def __init__(self) -> None:
            self.frame: object | None = None
            self.hidden = True

        def setFrame_(self, frame: object) -> None:
            self.frame = frame

        def setHidden_(self, hidden: bool) -> None:
            self.hidden = hidden

    class FakeValue:
        def __init__(self) -> None:
            self.value = ""
            self.color: object | None = None

        def setStringValue_(self, value: str) -> None:
            self.value = value

        def setTextColor_(self, color: object) -> None:
            self.color = color

    import voice_chess_cua.macos.overlay as overlay_module

    assert tuple(name for name, _ in overlay_module._HUD_ROWS) == (
        "VOICE",
        "TURN",
        "HEARD",
    )

    paths: list[list[tuple[str, float, float]]] = []

    def create_path() -> list[tuple[str, float, float]]:
        path: list[tuple[str, float, float]] = []
        paths.append(path)
        return path

    def add_path_point(
        path: list[tuple[str, float, float]],
        transform: object,
        x: float,
        y: float,
        *,
        operation: str,
    ) -> None:
        assert transform is None
        path.append((operation, x, y))

    quartz = SimpleNamespace(
        CGPathCreateMutable=create_path,
        CGPathMoveToPoint=lambda path, transform, x, y: add_path_point(
            path, transform, x, y, operation="move"
        ),
        CGPathAddLineToPoint=lambda path, transform, x, y: add_path_point(
            path, transform, x, y, operation="line"
        ),
    )
    appkit = SimpleNamespace(NSPanel=object, NSView=object, NSColor=FakeColors)
    backend = object.__new__(overlay_module._AppKitOverlayBackend)
    backend._appkit = appkit
    backend._quartz = quartz
    backend._style = OverlayStyle()
    backend._panel_class = None
    backend._view_class = None
    monkeypatch.setattr(overlay_module, "_APPKIT_OVERLAY_CLASSES", None)
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(super=super))
    backend._make_classes()
    assert backend._view_class is not None

    waveform_layer = FakeLayer()
    board_layers = (FakeLayer(), FakeLayer(), FakeLayer())
    for layer in board_layers:
        layer.path = object()
    card = FakeCard()
    values = {name: FakeValue() for name in ("VOICE", "TURN", "HEARD")}
    view = SimpleNamespace(
        _hud_card=card,
        _hud_values=values,
        _waveform=waveform_layer,
        _grid=board_layers[0],
        _source=board_layers[1],
        _destination=board_layers[2],
        _labels=[],
    )
    presentation = SimpleNamespace(
        voice=HUDPhase.LISTENING.value,
        turn="White to move",
        last_move="-",
        heard="Move E2 to E4",
        waveform=(0.25, 1.0),
        is_error=False,
        is_busy=False,
    )
    hud_frame = Rect(20.0, 30.0, 286.0, 154.0)

    backend._view_class.updateHUDPresentation_frame_(view, presentation, hud_frame)
    waveform_path = waveform_layer.path
    backend._view_class.clearBoard(view)

    assert len(paths) == 1
    assert waveform_path == paths[0]
    assert waveform_layer.path is waveform_path
    assert waveform_layer.stroke_color == "green"
    assert paths[0][0][0] == "move"
    assert paths[0][0][1] < paths[0][-2][1]
    assert all(layer.path is None for layer in board_layers)
    assert card.hidden is False
    assert values["HEARD"].value == "Move E2 to E4"


def test_appkit_backend_keeps_hud_updates_isolated_from_board_model() -> None:
    class FakeView:
        def __init__(self) -> None:
            self.hud_updates: list[tuple[object, Rect]] = []
            self.model_updates: list[object] = []
            self.clear_board_count = 0

        def updateHUDPresentation_frame_(
            self, presentation: object, frame: Rect
        ) -> None:
            self.hud_updates.append((presentation, frame))

        def updateModel_(self, model: object) -> None:
            self.model_updates.append(model)

        def clearBoard(self) -> None:
            self.clear_board_count += 1

    class FakePanel:
        def __init__(self) -> None:
            self.order_front_count = 0

        def orderFrontRegardless(self) -> None:
            self.order_front_count += 1

    import voice_chess_cua.macos.overlay as overlay_module

    frame = Rect(20.0, 30.0, 286.0, 154.0)
    presentation = present_hud(HUDState())
    view = FakeView()
    backend = object.__new__(overlay_module._AppKitOverlayBackend)
    panel = FakePanel()
    backend._view = view
    backend._panel = panel
    backend._hud_frame = frame

    backend._update_hud(presentation)
    backend._clear_board()

    assert view.hud_updates == [(presentation, frame)]
    assert view.model_updates == []
    assert view.clear_board_count == 1
    assert view.hud_updates[-1] == (presentation, frame)
    assert panel.order_front_count == 1


async def test_hud_updates_eagerly_reach_backend_and_board_clear_preserves_panel() -> (
    None
):
    backend = OverlayBackend()
    overlay = BoardOverlay(backend)
    state = reduce_hud(
        HUDState(),
        HUDUpdate(
            phase=HUDPhase.LISTENING,
            final_transcript="Move E2 to E4",
            turn="Black to move",
            last_move="White: E2 -> E4",
            board_available=True,
        ),
    )

    await overlay.update_hud(present_hud(state))
    await overlay.show_stable(
        BoardDetection(perspective_geometry(), 0.99, source_window_id=17)
    )
    await overlay.clear_board()

    assert backend.hud[-1].heard == "Move E2 to E4"
    assert backend.hud[-1].turn == "Black to move"
    assert backend.clear_board_count == 1
    assert backend.hide_count == 0


def test_standalone_hud_uses_visible_frame_top_right() -> None:
    from voice_chess_cua.macos.overlay import _standalone_hud_frame

    frame = _standalone_hud_frame(
        Rect(10, 30, 1400, 850),
        width=286,
        height=154,
        margin=12,
    )

    assert frame == Rect(1112, 42, 286, 154)

    compact = _standalone_hud_frame(
        Rect(10, 30, 200, 100),
        width=286,
        height=154,
        margin=12,
    )
    assert compact == Rect(10, 30, 200, 100)


def test_hud_layout_prefers_outside_board_and_clamps_fallback() -> None:
    visible = Rect(0, 0, 1400, 900)
    centered = Quad(Point(300, 150), Point(800, 150), Point(800, 650), Point(300, 650))
    near_right = Quad(
        Point(850, 150), Point(1350, 150), Point(1350, 650), Point(850, 650)
    )
    crowded = Quad(Point(30, 30), Point(1370, 30), Point(1370, 870), Point(30, 870))

    right = place_hud(centered, visible)
    left = place_hud(near_right, visible)
    fallback = place_hud(crowded, visible)

    assert right.frame.x > 800
    assert not right.overlaps_board
    assert left.frame.max_x < 850
    assert not left.overlaps_board
    assert fallback.overlaps_board
    assert 0 <= fallback.frame.min_x < fallback.frame.max_x <= visible.max_x
    assert 0 <= fallback.frame.min_y < fallback.frame.max_y <= visible.max_y


class VariableAudioBackend:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[object], None]] = []
        self.stop_count = 0

    def start(self, callback: Callable[[object], None]) -> None:
        self.callbacks.append(callback)

    def stop(self) -> None:
        self.stop_count += 1

    def decode(self, buffer: object) -> tuple[list[float], float]:
        assert isinstance(buffer, SimpleNamespace)
        return cast(list[float], buffer.samples), cast(float, buffer.sample_rate)

    def duration(self, buffer: object) -> float:
        assert isinstance(buffer, SimpleNamespace)
        samples = cast(list[float], buffer.samples)
        return len(samples) / cast(float, buffer.sample_rate)


class BlockingDecodeAudioBackend(VariableAudioBackend):
    def __init__(self) -> None:
        super().__init__()
        self.decode_started = threading.Event()
        self.release_decode = threading.Event()

    def decode(self, buffer: object) -> tuple[list[float], float]:
        self.decode_started.set()
        if not self.release_decode.wait(timeout=1.0):
            raise TimeoutError("test did not release audio decode")
        return super().decode(buffer)


class AudioBackend:
    def __init__(self) -> None:
        self.callback = None
        self.stopped = False

    def start(self, callback) -> None:
        self.callback = callback

    def stop(self) -> None:
        self.stopped = True

    def decode(self, buffer: object) -> tuple[list[float], float]:
        assert buffer == "buffer"
        return [0.25] * FRAMES_PER_CHUNK, 24_000

    def duration(self, buffer: object) -> float:
        assert buffer == "buffer"
        return 0.021


async def test_audio_callback_handoff_produces_exact_pcm_frame() -> None:
    backend = AudioBackend()
    audio = AudioCaptureService(backend)
    await audio.start()
    assert backend.callback is not None

    backend.callback("buffer")
    frame = await anext(audio.frames())
    await audio.stop()
    await audio.drain()

    assert len(frame) == BYTES_PER_CHUNK
    assert frame[:2] == b"\xff\x1f"
    assert backend.stopped


async def test_audio_callback_drops_buffers_captured_while_transaction_busy() -> None:
    backend = AudioBackend()
    audio = AudioCaptureService(backend)
    await audio.start()
    assert backend.callback is not None

    audio.set_transaction_busy(True)
    backend.callback("buffer")
    audio.set_transaction_busy(False)
    backend.callback("buffer")
    await audio.stop()
    frames = [frame async for frame in audio.frames()]

    assert frames == [b"\xff\x1f" * FRAMES_PER_CHUNK]


async def test_audio_stop_fifo_flushes_resampler_and_even_pcm_tail_once() -> None:
    backend = VariableAudioBackend()
    audio = AudioCaptureService(backend)
    await audio.start()
    callback = backend.callbacks[-1]
    first = SimpleNamespace(samples=[0.25] * 500, sample_rate=12_000)
    second = SimpleNamespace(samples=[0.5] * 500, sample_rate=12_000)
    late = SimpleNamespace(samples=[0.75] * 500, sample_rate=12_000)

    callback(first)
    callback(second)
    await audio.stop()
    await audio.stop()
    callback(late)
    frames = [frame async for frame in audio.frames()]

    expected = float_samples_to_pcm16le(
        resample_linear(first.samples + second.samples, 12_000)
    )
    assert b"".join(frames) == expected
    assert [len(frame) for frame in frames] == [
        BYTES_PER_CHUNK,
        len(expected) - BYTES_PER_CHUNK,
    ]
    assert 0 < len(frames[-1]) < BYTES_PER_CHUNK
    assert len(frames[-1]) % 2 == 0
    assert backend.stop_count == 1


async def test_audio_reuse_rejects_post_stop_and_old_generation_callbacks() -> None:
    backend = VariableAudioBackend()
    audio = AudioCaptureService(backend)
    first = SimpleNamespace(samples=[0.1, 0.1], sample_rate=24_000)
    stale = SimpleNamespace(samples=[0.9, 0.9], sample_rate=24_000)
    second = SimpleNamespace(samples=[0.2, 0.2], sample_rate=24_000)

    await audio.start()
    old_callback = backend.callbacks[-1]
    old_frames = audio.frames()
    old_callback(first)
    await audio.stop()
    old_callback(stale)

    await audio.start()
    current_callback = backend.callbacks[-1]
    current_frames = audio.frames()
    old_callback(stale)
    current_callback(second)
    await audio.stop()
    first_frames = [frame async for frame in old_frames]
    second_frames = [frame async for frame in current_frames]

    assert first_frames == [float_samples_to_pcm16le(first.samples)]
    assert second_frames == [float_samples_to_pcm16le(second.samples)]
    assert backend.stop_count == 2


async def test_audio_drain_waits_for_in_flight_decode_and_terminal_consumption() -> (
    None
):
    backend = BlockingDecodeAudioBackend()
    audio = AudioCaptureService(backend)
    await audio.start()
    callback = backend.callbacks[-1]
    sample = SimpleNamespace(samples=[0.25] * FRAMES_PER_CHUNK, sample_rate=24_000)

    async def consume() -> list[bytes]:
        return [frame async for frame in audio.frames()]

    consumer = asyncio.create_task(consume())
    callback(sample)
    assert await asyncio.to_thread(backend.decode_started.wait, 0.2)
    await audio.stop()
    draining = asyncio.create_task(audio.drain())
    await asyncio.sleep(0)
    assert not draining.done()

    backend.release_decode.set()
    assert await consumer == [float_samples_to_pcm16le(sample.samples)]
    await asyncio.wait_for(draining, timeout=0.2)
    assert backend.stop_count == 1


async def test_audio_drain_preserves_stop_marker_for_waiting_iterator() -> None:
    backend = AudioBackend()
    audio = AudioCaptureService(backend)
    await audio.start()
    frames = audio.frames()
    waiting = asyncio.create_task(anext(frames))
    await asyncio.sleep(0)

    await audio.stop()
    await audio.drain()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=0.2)
    assert backend.stopped


async def test_audio_overrun_terminates_stream_with_explicit_error() -> None:
    backend = AudioBackend()
    audio = AudioCaptureService(backend, maximum_buffered_duration=0.08)
    await audio.start()
    assert backend.callback is not None

    for _ in range(4):
        backend.callback("buffer")

    with pytest.raises(AudioBufferOverrunError):
        await anext(audio.frames())

    await audio.stop()
    await audio.drain()


def test_macos_application_module_import_does_not_import_pyobjc(monkeypatch) -> None:
    native_names = {
        "AppKit",
        "ApplicationServices",
        "AVFoundation",
        "Foundation",
        "Quartz",
        "ScreenCaptureKit",
        "Security",
    }
    for module_name in tuple(sys.modules):
        if module_name == "voice_chess_cua.macos" or module_name.startswith(
            "voice_chess_cua.macos."
        ):
            sys.modules.pop(module_name)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.partition(".")[0] in native_names:
            raise AssertionError(f"eager native import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    imported = importlib.import_module("voice_chess_cua.macos.application")

    assert imported.CHESS_BUNDLE_IDENTIFIER == "com.apple.Chess"
