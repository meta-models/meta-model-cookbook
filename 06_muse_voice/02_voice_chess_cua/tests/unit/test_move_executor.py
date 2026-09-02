# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass, field, replace
from types import SimpleNamespace
from typing import Any

import pytest

from voice_chess_cua.automation.move_executor import (
    ChessMoveExecutor,
    MoveExecutionBlocked,
    MoveExecutionReason,
    MoveExecutionUnconfirmed,
    MoveExecutorPolicy,
    MoveValidation,
    PartialMoveExecution,
    PostedEventKind,
    PreparedMove,
)
from voice_chess_cua.domain.chess import ChessMove, ChessSquare
from voice_chess_cua.domain.game_state import ChessPiece, PieceColor, PieceKind
from voice_chess_cua.domain.geometry import (
    BoardDetection,
    BoardGeometry,
    Point,
    Quad,
    Rect,
)


@dataclass(frozen=True, slots=True)
class Status:
    is_frontmost: bool = True
    process_identifier: int | None = 10


@dataclass(frozen=True, slots=True)
class Window:
    window_id: int = 42
    frame: Rect = field(default_factory=lambda: Rect(0, 0, 600, 600))
    process_id: int = 10


class Application:
    def __init__(
        self,
        *,
        activation: Status | BaseException | None = None,
        statuses: list[Status | BaseException] | None = None,
    ) -> None:
        self.activation = Status() if activation is None else activation
        self.statuses = list(statuses or [Status(), Status(), Status()])
        self.activate_calls: list[float] = []

    async def activate(self, timeout: float = 3.0) -> Status:
        self.activate_calls.append(timeout)
        if isinstance(self.activation, BaseException):
            raise self.activation
        return self.activation

    async def status(self) -> Status:
        if not self.statuses:
            return Status()
        value = self.statuses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class Locator:
    def __init__(self, windows: list[Window | BaseException] | None = None) -> None:
        self.windows = list(windows or [Window(), Window(), Window()])
        self.expected_process_ids: list[int | None] = []

    async def locate(self, expected_process_id: int | None = None) -> Window:
        self.expected_process_ids.append(expected_process_id)
        value = self.windows.pop(0) if len(self.windows) > 1 else self.windows[0]
        if isinstance(value, BaseException):
            raise value
        return value


class Tracker:
    def __init__(self, states: list[Any]) -> None:
        self.states = list(states)
        self.calls = 0

    async def force_fresh_detection(self) -> object:
        self.calls += 1
        value = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        if isinstance(value, BaseException):
            raise value
        return value


class SnapshotProbe:
    def __init__(
        self,
        snapshots: list[tuple[str, Mapping[str, str]]] | None = None,
    ) -> None:
        self.snapshots = list(snapshots or [game_snapshot()])
        self.process_identifiers: list[int] = []

    async def game_snapshot(
        self,
        process_identifier: int,
    ) -> tuple[str, Mapping[str, str]]:
        self.process_identifiers.append(process_identifier)
        value = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        return value


class BlockingSnapshotProbe(SnapshotProbe):
    def __init__(
        self, snapshots: list[tuple[str, Mapping[str, str]]] | None = None
    ) -> None:
        super().__init__(snapshots)
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def game_snapshot(
        self,
        process_identifier: int,
    ) -> tuple[str, Mapping[str, str]]:
        self.calls += 1
        if self.calls == 2:
            self.entered.set()
            await self.release.wait()
        return await super().game_snapshot(process_identifier)


class SquareResolver:
    """Resolves a point the way Accessibility hit testing does.

    A point lands on the square that contains it, unless `covers` says a piece
    hides that square from the given depth onwards, in which case the point
    resolves to the square the piece stands on.
    """

    def __init__(
        self,
        *,
        geometry: BoardGeometry | None = None,
        covers: Mapping[str, tuple[str, float]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.geometry = geometry or detection().geometry
        self.covers = dict(covers or {})
        self.error = error
        self.points: list[Point] = []

    async def square_at_point(
        self, process_identifier: int, point: Point
    ) -> str | None:
        del process_identifier
        if self.error is not None:
            raise self.error
        self.points.append(point)
        for square in ChessSquare.all():
            corners = self.geometry.corners_of(square)
            if not corners.contains(point):
                continue
            notation = square.notation.lower()
            hidden = self.covers.get(notation)
            if hidden is None:
                return notation
            covering, from_depth = hidden
            back, front = corners.top_left.y, corners.bottom_left.y
            depth = (point.y - back) / (front - back)
            return covering if depth >= from_depth else notation
        return None


class Poster:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.points: list[Point] = []
        self.calls = 0
        self.fail_on_call = fail_on_call
        self.process_identifiers: list[int] = []

    async def click(self, point: Point, process_identifier: int) -> None:
        self.process_identifiers.append(process_identifier)
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise OSError("CGEvent creation failed")
        self.points.append(point)


class Postcondition:
    def __init__(self, *, confirmed: bool = True) -> None:
        self.confirmed = confirmed
        self.captures: list[tuple[int, ChessMove]] = []
        self.waits: list[tuple[int, ChessMove, object]] = []
        self.before = {"e2": "white pawn, e2", "e4": "e4"}

    async def capture(self, process_identifier: int, move: ChessMove) -> object:
        self.captures.append((process_identifier, move))
        return self.before

    async def wait_until_applied(
        self,
        process_identifier: int,
        move: ChessMove,
        before: object,
    ) -> bool:
        self.waits.append((process_identifier, move, before))
        return self.confirmed


class BlockingPoster(Poster):
    def __init__(self, *, block_on_call: int = 1) -> None:
        super().__init__()
        self.block_on_call = block_on_call
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def click(self, point: Point, process_identifier: int) -> None:
        self.process_identifiers.append(process_identifier)
        self.calls += 1
        if self.calls == self.block_on_call:
            self.entered.set()
            await self.release.wait()
        self.points.append(point)


@dataclass(slots=True)
class Fixture:
    executor: ChessMoveExecutor
    move: ChessMove
    poster: Poster
    snapshot_probe: SnapshotProbe
    square_resolver: SquareResolver
    events: list[Any]
    sleeps: list[float]


def detection(
    *,
    confidence: float = 0.99,
    captured_at: float = 1_000,
    source_window_id: int = 42,
    geometry: Any | None = None,
) -> BoardDetection:
    return BoardDetection(
        geometry=geometry
        or BoardGeometry(
            Quad(
                Point(100, 100),
                Point(500, 100),
                Point(500, 500),
                Point(100, 500),
            )
        ),
        confidence=confidence,
        captured_at=captured_at,
        source_window_id=source_window_id,
    )


def ready(value: BoardDetection | None, *, generation: int = 1) -> object:
    return SimpleNamespace(ready_detection=value, generation=generation)


def game_snapshot(
    *,
    title: str = "Game 1 | Sample Player - Computer (White to Move)",
    overrides: Mapping[str, str] | None = None,
) -> tuple[str, Mapping[str, str]]:
    labels = {
        square.notation.lower(): square.notation.lower() for square in ChessSquare.all()
    }
    labels["e2"] = "white pawn, e2"
    if overrides is not None:
        labels.update(overrides)
    return title, labels


def make_fixture(
    *,
    accessibility: bool = True,
    screen_recording: bool = True,
    application: Application | None = None,
    locator: Locator | None = None,
    tracker: Tracker | None = None,
    poster: Poster | None = None,
    postcondition: Postcondition | None = None,
    snapshot_probe: SnapshotProbe | None = None,
    square_resolver: SquareResolver | None = None,
    display_contains_board=lambda quad: True,
    sleep_error: BaseException | None = None,
    policy: MoveExecutorPolicy | None = None,
    clock=lambda: 1_000,
) -> Fixture:
    events: list[Any] = []
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        if sleep_error is not None:
            raise sleep_error

    poster = poster or Poster()
    postcondition = postcondition or Postcondition()
    snapshot_probe = snapshot_probe or SnapshotProbe()
    square_resolver = square_resolver or SquareResolver()
    executor = ChessMoveExecutor(
        application_controller=application or Application(),
        window_locator=locator or Locator(),
        board_tracker=tracker or Tracker([ready(detection())]),
        event_poster=poster,
        display_contains_board=display_contains_board,
        postcondition=postcondition,
        snapshot_probe=snapshot_probe,
        square_resolver=square_resolver,
        policy=policy
        or MoveExecutorPolicy(
            minimum_board_confidence=0.85,
            required_stable_detections=1,
            maximum_detection_age=1,
            click_delay=0.15,
            activation_timeout=1,
            window_tolerance=1,
        ),
        accessibility_trusted=lambda: accessibility,
        screen_recording_allowed=lambda: screen_recording,
        reporter=events.append,
        sleep=sleep,
        clock=clock,
    )
    return Fixture(
        executor=executor,
        move=ChessMove(ChessSquare.parse("E2"), ChessSquare.parse("E4")),
        poster=poster,
        snapshot_probe=snapshot_probe,
        square_resolver=square_resolver,
        events=events,
        sleeps=sleeps,
    )


async def execute_move(fixture: Fixture):
    prepared = await fixture.executor.prepare(fixture.move)
    return await fixture.executor.execute_prepared(prepared)


async def test_success_posts_source_then_waits_then_posts_destination() -> None:
    fixture = make_fixture()

    result = await execute_move(fixture)

    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]
    assert fixture.poster.process_identifiers == [10, 10]
    assert fixture.sleeps == [0.15]
    assert result.move == fixture.move
    assert result.source_event.kind is PostedEventKind.SOURCE
    assert result.destination_event.kind is PostedEventKind.DESTINATION
    assert [event.validation for event in fixture.events if event.validation] == [
        MoveValidation.ACCESSIBILITY_PERMISSION,
        MoveValidation.SCREEN_RECORDING_PERMISSION,
        MoveValidation.CHESS_ACTIVATED,
        MoveValidation.INITIAL_WINDOW_SELECTED,
        MoveValidation.BOARD_FRESH_AND_STABLE,
        MoveValidation.BOARD_MATCHES_WINDOW,
        MoveValidation.SQUARE_GEOMETRY,
        MoveValidation.POINTS_INSIDE_WINDOW,
        MoveValidation.BOARD_WITHIN_SINGLE_DISPLAY,
        MoveValidation.CLICK_TARGETS_RESOLVED,
        MoveValidation.CHESS_FOCUSED_BEFORE_SOURCE,
        MoveValidation.WINDOW_REVALIDATED_BEFORE_SOURCE,
        MoveValidation.CHESS_FOCUSED_IMMEDIATELY_BEFORE_SOURCE,
        MoveValidation.CHESS_FOCUSED_AFTER_SOURCE,
        MoveValidation.POST_SOURCE_WINDOW_SELECTED,
        MoveValidation.CHESS_FOCUSED_BEFORE_DESTINATION,
        MoveValidation.WINDOW_UNCHANGED_AFTER_SOURCE,
        MoveValidation.MOVE_CONFIRMED,
    ]


@pytest.mark.parametrize(
    ("fixture_overrides", "reason"),
    [
        ({"accessibility": False}, MoveExecutionReason.ACCESSIBILITY_DENIED),
        ({"screen_recording": False}, MoveExecutionReason.SCREEN_RECORDING_DENIED),
        (
            {"application": Application(activation=OSError("activate"))},
            MoveExecutionReason.CHESS_ACTIVATION_FAILED,
        ),
        (
            {"application": Application(activation=Status(is_frontmost=False))},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"application": Application(activation=Status(process_identifier=None))},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"application": Application(activation=Status(process_identifier=0))},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"application": Application(activation=Status(process_identifier=-1))},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"application": Application(activation=Status(process_identifier=True))},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"locator": Locator([LookupError("none")])},
            MoveExecutionReason.WINDOW_SELECTION_FAILED,
        ),
        (
            {"locator": Locator([Window(process_id=11)])},
            MoveExecutionReason.WINDOW_SELECTION_FAILED,
        ),
        (
            {"tracker": Tracker([ready(None)])},
            MoveExecutionReason.BOARD_NOT_READY,
        ),
        (
            {"tracker": Tracker([ready(detection(confidence=0.84))])},
            MoveExecutionReason.BOARD_NOT_READY,
        ),
        (
            {"tracker": Tracker([ready(detection(captured_at=998.999))])},
            MoveExecutionReason.BOARD_NOT_READY,
        ),
        (
            {"tracker": Tracker([ready(detection(captured_at=1_000.001))])},
            MoveExecutionReason.BOARD_NOT_READY,
        ),
        (
            {"tracker": Tracker([ready(detection(source_window_id=99))])},
            MoveExecutionReason.WRONG_WINDOW,
        ),
        (
            {"locator": Locator([Window(frame=Rect(0, 0, 200, 200))])},
            MoveExecutionReason.POINT_OUTSIDE_WINDOW,
        ),
        (
            {"display_contains_board": lambda quad: False},
            MoveExecutionReason.BOARD_SPANS_DISPLAYS,
        ),
        (
            {"application": Application(statuses=[Status(is_frontmost=False)])},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"application": Application(statuses=[Status(process_identifier=11)])},
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"locator": Locator([Window(), Window(window_id=43)])},
            MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE,
        ),
        (
            {"locator": Locator([Window(), Window(frame=Rect(1.01, 0, 600, 600))])},
            MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE,
        ),
        (
            {
                "application": Application(
                    statuses=[Status(), Status(is_frontmost=False)]
                )
            },
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"poster": Poster(fail_on_call=1)},
            MoveExecutionReason.EVENT_POST_FAILED,
        ),
    ],
)
async def test_every_pre_source_failure_posts_zero_events(
    fixture_overrides: dict[str, Any],
    reason: MoveExecutionReason,
) -> None:
    fixture = make_fixture(**fixture_overrides)

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execute_move(fixture)

    assert caught.value.reason is reason
    assert fixture.poster.points == []
    assert [event.posted_event for event in fixture.events if event.posted_event] == []


@pytest.mark.parametrize("process_identifier", (0, -1, True))
async def test_invalid_activation_pid_stops_before_window_snapshot_or_input(
    process_identifier: int,
) -> None:
    locator = Locator()
    snapshot_probe = SnapshotProbe()
    fixture = make_fixture(
        application=Application(
            activation=Status(process_identifier=process_identifier)
        ),
        locator=locator,
        snapshot_probe=snapshot_probe,
    )

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.prepare(fixture.move)

    assert caught.value.reason is MoveExecutionReason.CHESS_NOT_FRONTMOST
    assert locator.expected_process_ids == []
    assert snapshot_probe.process_identifiers == []
    assert fixture.poster.points == []


async def test_postcondition_confirms_actual_board_state_change() -> None:
    postcondition = Postcondition()
    fixture = make_fixture(postcondition=postcondition)

    result = await execute_move(fixture)

    assert result.move == fixture.move
    assert postcondition.captures == [(10, fixture.move)]
    assert postcondition.waits == [(10, fixture.move, postcondition.before)]
    assert MoveValidation.MOVE_CONFIRMED in [
        event.validation for event in fixture.events if event.validation
    ]


async def test_unchanged_board_state_is_not_reported_as_success() -> None:
    postcondition = Postcondition(confirmed=False)
    fixture = make_fixture(postcondition=postcondition)

    with pytest.raises(MoveExecutionUnconfirmed) as caught:
        await execute_move(fixture)

    assert caught.value.reason is MoveExecutionReason.MOVE_NOT_CONFIRMED
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]
    assert MoveValidation.MOVE_CONFIRMED not in [
        event.validation for event in fixture.events if event.validation
    ]


async def test_invalid_square_mapping_posts_zero_events() -> None:
    class InvalidGeometry:
        quad = Quad(Point(100, 100), Point(500, 100), Point(500, 500), Point(100, 500))

        def aim_point(self, square: ChessSquare, depth: float = 0.5) -> Point:
            del square, depth
            raise ValueError("cannot map")

        def contains(self, point: Point) -> bool:
            del point
            return False

    fixture = make_fixture(
        tracker=Tracker([ready(detection(geometry=InvalidGeometry()))])
    )

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execute_move(fixture)

    assert caught.value.reason is MoveExecutionReason.INVALID_SQUARE_GEOMETRY
    assert fixture.poster.points == []


async def test_a_square_hidden_by_a_piece_is_clicked_behind_the_piece() -> None:
    fixture = make_fixture(square_resolver=SquareResolver(covers={"e2": ("e1", 0.4)}))

    result = await execute_move(fixture)

    assert result.source_event.point == Point(325, 417)
    assert fixture.poster.points == [Point(325, 417), Point(325, 325)]


async def test_a_fully_hidden_square_posts_zero_events() -> None:
    fixture = make_fixture(square_resolver=SquareResolver(covers={"e2": ("e1", 0.0)}))

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execute_move(fixture)

    assert caught.value.reason is MoveExecutionReason.SQUARE_NOT_CLICKABLE
    assert fixture.poster.points == []


async def test_a_point_owned_by_another_process_posts_zero_events() -> None:
    class ForeignWindowResolver:
        async def square_at_point(
            self, process_identifier: int, point: Point
        ) -> str | None:
            del process_identifier, point
            return None

    fixture = make_fixture(square_resolver=ForeignWindowResolver())

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execute_move(fixture)

    assert caught.value.reason is MoveExecutionReason.SQUARE_NOT_CLICKABLE
    assert fixture.poster.points == []


async def test_an_unreadable_hit_test_posts_zero_events() -> None:
    fixture = make_fixture(
        square_resolver=SquareResolver(error=OSError("hit test failed"))
    )

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execute_move(fixture)

    assert caught.value.reason is MoveExecutionReason.SQUARE_NOT_CLICKABLE
    assert isinstance(caught.value.underlying_error, OSError)
    assert fixture.poster.points == []


async def test_a_square_that_becomes_hidden_after_preparation_withholds_input() -> None:
    resolver = SquareResolver()
    fixture = make_fixture(square_resolver=resolver)
    prepared = await fixture.executor.prepare(fixture.move)
    resolver.covers["e2"] = ("e1", 0.4)

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(prepared)

    assert caught.value.reason is MoveExecutionReason.PREPARED_BASELINE_CHANGED
    assert fixture.poster.points == []


@pytest.mark.parametrize(
    ("fixture_overrides", "reason"),
    [
        (
            {"sleep_error": asyncio.CancelledError()},
            MoveExecutionReason.CANCELLED,
        ),
        (
            {
                "application": Application(
                    statuses=[
                        Status(),
                        Status(),
                        Status(),
                        Status(),
                        Status(is_frontmost=False),
                    ]
                )
            },
            MoveExecutionReason.CHESS_LOST_FOCUS_AFTER_SOURCE,
        ),
        (
            {"locator": Locator([Window(), Window(), Window(), LookupError("gone")])},
            MoveExecutionReason.WINDOW_SELECTION_FAILED,
        ),
        (
            {
                "application": Application(
                    statuses=[
                        Status(),
                        Status(),
                        Status(),
                        Status(),
                        Status(),
                        Status(is_frontmost=False),
                    ]
                )
            },
            MoveExecutionReason.CHESS_LOST_FOCUS_AFTER_SOURCE,
        ),
        (
            {"locator": Locator([Window(), Window(), Window(), Window(window_id=43)])},
            MoveExecutionReason.WINDOW_CHANGED_AFTER_SOURCE,
        ),
        (
            {
                "locator": Locator(
                    [
                        Window(),
                        Window(),
                        Window(),
                        Window(frame=Rect(1.01, 0, 600, 600)),
                    ]
                )
            },
            MoveExecutionReason.WINDOW_CHANGED_AFTER_SOURCE,
        ),
        (
            {"poster": Poster(fail_on_call=2)},
            MoveExecutionReason.EVENT_POST_FAILED,
        ),
    ],
)
async def test_every_post_source_failure_is_typed_partial(
    fixture_overrides: dict[str, Any],
    reason: MoveExecutionReason,
) -> None:
    fixture = make_fixture(**fixture_overrides)

    with pytest.raises(PartialMoveExecution) as caught:
        await execute_move(fixture)

    partial = caught.value
    assert partial.reason is reason
    assert partial.move == fixture.move
    assert partial.source_event.kind is PostedEventKind.SOURCE
    assert partial.source_event.point == Point(325, 425)
    assert fixture.poster.points == [Point(325, 425)]
    assert [
        event.posted_event.kind
        for event in fixture.events
        if event.posted_event is not None
    ] == [PostedEventKind.SOURCE]


async def test_cancellation_while_source_post_is_in_flight_waits_and_reports_partial() -> (
    None
):
    poster = BlockingPoster()
    fixture = make_fixture(poster=poster)
    execution = asyncio.create_task(execute_move(fixture))
    await poster.entered.wait()

    execution.cancel()
    await asyncio.sleep(0)
    assert execution.done() is False
    poster.release.set()

    with pytest.raises(PartialMoveExecution) as caught:
        await execution
    assert caught.value.reason is MoveExecutionReason.CANCELLED
    assert fixture.poster.points == [Point(325, 425)]


async def test_cancellation_while_destination_post_is_in_flight_reports_completed_move() -> (
    None
):
    poster = BlockingPoster(block_on_call=2)
    fixture = make_fixture(poster=poster)
    execution = asyncio.create_task(execute_move(fixture))
    await poster.entered.wait()

    execution.cancel()
    await asyncio.sleep(0)
    assert execution.done() is False
    poster.release.set()

    result = await execution
    assert result.destination_event.kind is PostedEventKind.DESTINATION
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


async def test_failing_reporter_cannot_change_input_control_flow() -> None:
    fixture = make_fixture()

    def broken_reporter(event: object) -> None:
        del event
        raise RuntimeError("telemetry failed")

    fixture.executor._reporter = broken_reporter
    result = await execute_move(fixture)

    assert result.destination_event.kind is PostedEventKind.DESTINATION
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


async def test_window_tolerance_is_inclusive() -> None:
    fixture = make_fixture(
        locator=Locator(
            [
                Window(),
                Window(),
                Window(),
                Window(frame=Rect(-1, 1, 599, 601)),
            ]
        )
    )

    result = await execute_move(fixture)

    assert result.destination_event.point == Point(325, 325)


async def test_executor_rejects_concurrent_input_instead_of_queueing_it() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_sleep(delay: float) -> None:
        assert delay == 0.15
        entered.set()
        await release.wait()

    fixture = make_fixture()
    fixture.executor._sleep = blocking_sleep
    first = asyncio.create_task(execute_move(fixture))
    await entered.wait()

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execute_move(fixture)
    assert caught.value.reason is MoveExecutionReason.ALREADY_EXECUTING
    assert fixture.poster.points == [Point(325, 425)]

    release.set()
    await first
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


async def test_prepare_omits_before_state_from_repr_and_posts_no_input() -> None:
    postcondition = Postcondition()
    fixture = make_fixture(postcondition=postcondition)

    prepared = await fixture.executor.prepare(fixture.move)

    assert isinstance(prepared, PreparedMove)
    assert prepared.process_identifier == 10
    assert prepared.window_id == 42
    assert prepared.window_frame == Rect(0, 0, 600, 600)
    assert prepared.ax_title == "Game 1 | Sample Player - Computer (White to Move)"
    assert len(prepared.square_snapshot) == 64
    assert tuple(square for square, _ in prepared.square_snapshot) == ChessSquare.all()
    assert prepared.game_state.piece_at(ChessSquare.parse("E2")) == ChessPiece(
        PieceColor.WHITE,
        PieceKind.PAWN,
    )
    assert prepared.tracking_generation == 1
    assert fixture.poster.points == []
    assert postcondition.captures == [(10, fixture.move)]
    assert "_before_state" not in repr(prepared)
    with pytest.raises(FrozenInstanceError):
        prepared.ax_title = "changed"  # type: ignore[misc]


async def test_execute_prepared_preserves_click_and_postcondition_semantics() -> None:
    postcondition = Postcondition()
    fixture = make_fixture(postcondition=postcondition)
    prepared = await fixture.executor.prepare(fixture.move)

    result = await fixture.executor.execute_prepared(prepared)

    assert result.move == fixture.move
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]
    assert postcondition.waits == [(10, fixture.move, postcondition.before)]


async def test_new_prepare_replaces_previous_pending_capability() -> None:
    fixture = make_fixture()
    first = await fixture.executor.prepare(fixture.move)
    second_move = ChessMove(ChessSquare.parse("D2"), ChessSquare.parse("D4"))
    second = await fixture.executor.prepare(second_move)

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(first)

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert fixture.poster.points == []

    result = await fixture.executor.execute_prepared(second)

    assert result.move == second_move
    assert fixture.poster.points == [Point(275, 425), Point(275, 325)]


async def test_busy_rejection_preserves_pending_capability() -> None:
    snapshot_probe = BlockingSnapshotProbe()
    fixture = make_fixture(snapshot_probe=snapshot_probe)
    prepared = await fixture.executor.prepare(fixture.move)
    next_prepare = asyncio.create_task(fixture.executor.prepare(fixture.move))
    await snapshot_probe.entered.wait()

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(prepared)

    assert caught.value.reason is MoveExecutionReason.ALREADY_EXECUTING
    assert fixture.poster.points == []

    next_prepare.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_prepare

    result = await fixture.executor.execute_prepared(prepared)

    assert result.move == fixture.move
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


async def test_non_prepared_move_is_rejected_before_input() -> None:
    fixture = make_fixture()

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(object())  # type: ignore[arg-type]

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert fixture.poster.points == []


async def test_completed_prepared_move_cannot_be_replayed() -> None:
    fixture = make_fixture()
    prepared = await fixture.executor.prepare(fixture.move)

    result = await fixture.executor.execute_prepared(prepared)
    assert result.move == fixture.move

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(prepared)

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


async def test_forged_none_owner_token_is_rejected_after_pending_token_is_consumed() -> (
    None
):
    fixture = make_fixture()
    prepared = await fixture.executor.prepare(fixture.move)

    result = await fixture.executor.execute_prepared(prepared)
    assert result.move == fixture.move
    click_count = len(fixture.poster.points)

    forged = replace(prepared, _owner_token=None)
    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(forged)

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert len(fixture.poster.points) == click_count


async def test_unconfirmed_prepared_move_cannot_be_replayed() -> None:
    fixture = make_fixture(postcondition=Postcondition(confirmed=False))
    prepared = await fixture.executor.prepare(fixture.move)

    with pytest.raises(MoveExecutionUnconfirmed):
        await fixture.executor.execute_prepared(prepared)

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(prepared)

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


async def test_foreign_executor_rejects_prepared_move_before_input() -> None:
    owner = make_fixture()
    foreign = make_fixture()
    prepared = await owner.executor.prepare(owner.move)

    with pytest.raises(MoveExecutionBlocked) as caught:
        await foreign.executor.execute_prepared(prepared)

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert foreign.poster.points == []


async def test_concurrent_execute_prepared_consumes_capability_once() -> None:
    snapshot_probe = BlockingSnapshotProbe()
    fixture = make_fixture(snapshot_probe=snapshot_probe)
    prepared = await fixture.executor.prepare(fixture.move)
    first = asyncio.create_task(fixture.executor.execute_prepared(prepared))
    await snapshot_probe.entered.wait()

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(prepared)

    assert caught.value.reason is MoveExecutionReason.INVALID_PREPARED_MOVE
    assert fixture.poster.points == []

    snapshot_probe.release.set()
    result = await first
    assert result.destination_event.kind is PostedEventKind.DESTINATION
    assert fixture.poster.points == [Point(325, 425), Point(325, 325)]


@pytest.mark.parametrize(
    ("fixture_overrides", "reason"),
    [
        (
            {"tracker": Tracker([ready(detection()), ready(None)])},
            MoveExecutionReason.BOARD_NOT_READY,
        ),
        (
            {
                "application": Application(
                    statuses=[Status(), Status(), Status(process_identifier=11)]
                )
            },
            MoveExecutionReason.CHESS_NOT_FRONTMOST,
        ),
        (
            {"locator": Locator([Window(), Window(), Window(window_id=43)])},
            MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE,
        ),
        (
            {
                "locator": Locator(
                    [Window(), Window(), Window(frame=Rect(0.01, 0, 600, 600))]
                )
            },
            MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE,
        ),
        (
            {
                "snapshot_probe": SnapshotProbe(
                    [
                        game_snapshot(),
                        game_snapshot(
                            title="Game 1 | Sample Player - Computer  (White to Move)"
                        ),
                    ]
                )
            },
            MoveExecutionReason.PREPARED_BASELINE_CHANGED,
        ),
        (
            {
                "snapshot_probe": SnapshotProbe(
                    [
                        game_snapshot(),
                        game_snapshot(overrides={"e2": " white   pawn, e2 "}),
                    ]
                )
            },
            MoveExecutionReason.PREPARED_BASELINE_CHANGED,
        ),
        (
            {
                "snapshot_probe": SnapshotProbe(
                    [
                        game_snapshot(),
                        game_snapshot(overrides={"e2": "e2", "e4": "white pawn, e4"}),
                    ]
                )
            },
            MoveExecutionReason.PREPARED_BASELINE_CHANGED,
        ),
        (
            {
                "tracker": Tracker(
                    [ready(detection(), generation=1), ready(detection(), generation=2)]
                )
            },
            MoveExecutionReason.PREPARED_BASELINE_CHANGED,
        ),
        (
            {
                "tracker": Tracker(
                    [
                        ready(detection()),
                        ready(
                            detection(
                                geometry=BoardGeometry(
                                    Quad(
                                        Point(101, 100),
                                        Point(501, 100),
                                        Point(501, 500),
                                        Point(101, 500),
                                    )
                                )
                            )
                        ),
                    ]
                )
            },
            MoveExecutionReason.PREPARED_BASELINE_CHANGED,
        ),
        (
            {
                "tracker": Tracker(
                    [ready(detection()), ready(detection(source_window_id=43))]
                )
            },
            MoveExecutionReason.WRONG_WINDOW,
        ),
    ],
)
async def test_prepared_baseline_mismatches_post_zero_events(
    fixture_overrides: dict[str, Any],
    reason: MoveExecutionReason,
) -> None:
    fixture = make_fixture(**fixture_overrides)
    prepared = await fixture.executor.prepare(fixture.move)

    with pytest.raises(MoveExecutionBlocked) as caught:
        await fixture.executor.execute_prepared(prepared)

    assert caught.value.reason is reason
    assert fixture.poster.points == []
    assert [event.posted_event for event in fixture.events if event.posted_event] == []


async def test_focus_loss_during_snapshot_recapture_posts_zero_events() -> None:
    snapshot_probe = BlockingSnapshotProbe()
    fixture = make_fixture(
        snapshot_probe=snapshot_probe,
        application=Application(
            statuses=[Status(), Status(), Status(), Status(is_frontmost=False)]
        ),
    )
    prepared = await fixture.executor.prepare(fixture.move)
    execution = asyncio.create_task(fixture.executor.execute_prepared(prepared))
    await snapshot_probe.entered.wait()

    snapshot_probe.release.set()

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execution
    assert caught.value.reason is MoveExecutionReason.CHESS_NOT_FRONTMOST
    assert fixture.poster.points == []


async def test_detection_that_ages_during_snapshot_recapture_posts_zero_events() -> (
    None
):
    now = [1_000.0]
    snapshot_probe = BlockingSnapshotProbe()
    fixture = make_fixture(snapshot_probe=snapshot_probe, clock=lambda: now[0])
    prepared = await fixture.executor.prepare(fixture.move)
    execution = asyncio.create_task(fixture.executor.execute_prepared(prepared))
    await snapshot_probe.entered.wait()

    now[0] = 1_001.01
    snapshot_probe.release.set()

    with pytest.raises(MoveExecutionBlocked) as caught:
        await execution
    assert caught.value.reason is MoveExecutionReason.BOARD_NOT_READY
    assert fixture.poster.points == []
