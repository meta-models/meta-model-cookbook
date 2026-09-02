# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Fail-closed, two-phase Apple Chess move execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from voice_chess_cua.domain.chess import ChessMove, ChessSquare
from voice_chess_cua.domain.game_state import ChessGameState
from voice_chess_cua.domain.geometry import BoardDetection, Point, Quad, Rect
from voice_chess_cua.macos.chess_state import (
    AppleChessSnapshot,
    parse_apple_chess_snapshot,
)
from voice_chess_cua.macos.permissions import (
    has_screen_recording_access,
    is_accessibility_trusted,
)


class MoveValidation(StrEnum):
    ACCESSIBILITY_PERMISSION = "accessibilityPermission"
    SCREEN_RECORDING_PERMISSION = "screenRecordingPermission"
    CHESS_ACTIVATED = "chessActivated"
    INITIAL_WINDOW_SELECTED = "initialWindowSelected"
    BOARD_FRESH_AND_STABLE = "boardFreshAndStable"
    BOARD_MATCHES_WINDOW = "boardMatchesWindow"
    SQUARE_GEOMETRY = "squareGeometry"
    POINTS_INSIDE_WINDOW = "pointsInsideWindow"
    CLICK_TARGETS_RESOLVED = "clickTargetsResolved"
    BOARD_WITHIN_SINGLE_DISPLAY = "boardWithinSingleDisplay"
    CHESS_FOCUSED_BEFORE_SOURCE = "chessFocusedBeforeSource"
    WINDOW_REVALIDATED_BEFORE_SOURCE = "windowRevalidatedBeforeSource"
    CHESS_FOCUSED_IMMEDIATELY_BEFORE_SOURCE = "chessFocusedImmediatelyBeforeSource"
    CHESS_FOCUSED_AFTER_SOURCE = "chessFocusedAfterSource"
    POST_SOURCE_WINDOW_SELECTED = "postSourceWindowSelected"
    CHESS_FOCUSED_BEFORE_DESTINATION = "chessFocusedBeforeDestination"
    WINDOW_UNCHANGED_AFTER_SOURCE = "windowUnchangedAfterSource"
    MOVE_CONFIRMED = "moveConfirmed"


class PostedEventKind(StrEnum):
    SOURCE = "source"
    DESTINATION = "destination"


@dataclass(frozen=True, slots=True)
class PostedEvent:
    kind: PostedEventKind
    square: ChessSquare
    point: Point


@dataclass(frozen=True, slots=True)
class MoveExecutionEvent:
    validation: MoveValidation | None = None
    posted_event: PostedEvent | None = None

    def __post_init__(self) -> None:
        if (self.validation is None) == (self.posted_event is None):
            raise ValueError("an execution event must contain exactly one event kind")

    @classmethod
    def validation_passed(cls, validation: MoveValidation) -> MoveExecutionEvent:
        return cls(validation=validation)

    @classmethod
    def event_posted(cls, event: PostedEvent) -> MoveExecutionEvent:
        return cls(posted_event=event)


class MoveExecutionReason(StrEnum):
    ACCESSIBILITY_DENIED = "accessibilityDenied"
    SCREEN_RECORDING_DENIED = "screenRecordingDenied"
    CHESS_ACTIVATION_FAILED = "chessActivationFailed"
    CHESS_NOT_FRONTMOST = "chessNotFrontmost"
    WINDOW_SELECTION_FAILED = "windowSelectionFailed"
    BOARD_NOT_READY = "boardNotReady"
    WRONG_WINDOW = "wrongWindow"
    INVALID_SQUARE_GEOMETRY = "invalidSquareGeometry"
    POINT_OUTSIDE_WINDOW = "pointOutsideWindow"
    SQUARE_NOT_CLICKABLE = "squareNotClickable"
    BOARD_SPANS_DISPLAYS = "boardSpansDisplays"
    WINDOW_CHANGED_BEFORE_SOURCE = "windowChangedBeforeSource"
    EVENT_POST_FAILED = "eventPostFailed"
    CHESS_LOST_FOCUS_AFTER_SOURCE = "chessLostFocusAfterSource"
    WINDOW_CHANGED_AFTER_SOURCE = "windowChangedAfterSource"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ALREADY_EXECUTING = "alreadyExecuting"
    MOVE_NOT_CONFIRMED = "moveNotConfirmed"
    INVALID_PREPARED_MOVE = "invalidPreparedMove"
    PREPARED_BASELINE_CHANGED = "preparedBaselineChanged"


_REASON_MESSAGES = {
    MoveExecutionReason.ACCESSIBILITY_DENIED: (
        "Accessibility permission is required before Voice Chess can click."
    ),
    MoveExecutionReason.SCREEN_RECORDING_DENIED: (
        "Screen Recording permission is required to revalidate the board."
    ),
    MoveExecutionReason.CHESS_ACTIVATION_FAILED: "Chess could not be activated safely.",
    MoveExecutionReason.CHESS_NOT_FRONTMOST: "Chess is not the frontmost application.",
    MoveExecutionReason.WINDOW_SELECTION_FAILED: (
        "Exactly one visible Apple Chess window is required."
    ),
    MoveExecutionReason.BOARD_NOT_READY: (
        "The board is not fresh, stable, and confident enough to click."
    ),
    MoveExecutionReason.WRONG_WINDOW: (
        "The detected board no longer belongs to the selected Chess window."
    ),
    MoveExecutionReason.INVALID_SQUARE_GEOMETRY: (
        "The requested square could not be mapped inside the detected board."
    ),
    MoveExecutionReason.POINT_OUTSIDE_WINDOW: (
        "A mapped square falls outside the current Chess window."
    ),
    MoveExecutionReason.SQUARE_NOT_CLICKABLE: (
        "A square is covered by a piece or another window and cannot be clicked safely."
    ),
    MoveExecutionReason.BOARD_SPANS_DISPLAYS: (
        "The detected board spans multiple displays and cannot be clicked safely."
    ),
    MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE: (
        "The Chess window changed during validation; no input was posted."
    ),
    MoveExecutionReason.EVENT_POST_FAILED: "macOS could not post the requested input event.",
    MoveExecutionReason.CHESS_LOST_FOCUS_AFTER_SOURCE: (
        "Chess lost focus after the source click; the destination was withheld."
    ),
    MoveExecutionReason.WINDOW_CHANGED_AFTER_SOURCE: (
        "The Chess window changed after the source click; the destination was withheld."
    ),
    MoveExecutionReason.CANCELLED: "Move execution was cancelled.",
    MoveExecutionReason.FAILED: "Move execution failed.",
    MoveExecutionReason.ALREADY_EXECUTING: "Another Chess input transaction is in progress.",
    MoveExecutionReason.MOVE_NOT_CONFIRMED: (
        "Apple Chess did not confirm the requested board-state change."
    ),
    MoveExecutionReason.INVALID_PREPARED_MOVE: (
        "The prepared Chess move is invalid, foreign, or already consumed."
    ),
    MoveExecutionReason.PREPARED_BASELINE_CHANGED: (
        "The prepared Chess state changed before input; no input was posted."
    ),
}


class MoveExecutionBlocked(RuntimeError):
    """A pre-source failure. The executor guarantees that it posted no click."""

    def __init__(
        self,
        reason: MoveExecutionReason,
        *,
        underlying_error: BaseException | None = None,
    ) -> None:
        super().__init__(_REASON_MESSAGES[reason])
        self.reason = reason
        self.underlying_error = underlying_error


class MoveExecutionUnconfirmed(RuntimeError):
    """Both clicks were posted, but Apple Chess did not confirm the move."""

    def __init__(
        self,
        *,
        move: ChessMove,
        detection: BoardDetection,
        source_event: PostedEvent,
        destination_event: PostedEvent,
    ) -> None:
        super().__init__(_REASON_MESSAGES[MoveExecutionReason.MOVE_NOT_CONFIRMED])
        self.move = move
        self.detection = detection
        self.source_event = source_event
        self.destination_event = destination_event
        self.reason = MoveExecutionReason.MOVE_NOT_CONFIRMED


class PartialMoveExecution(RuntimeError):
    """A source click completed, but the destination click was withheld or failed."""

    def __init__(
        self,
        *,
        move: ChessMove,
        detection: BoardDetection,
        source_event: PostedEvent,
        reason: MoveExecutionReason,
        underlying_error: BaseException,
    ) -> None:
        detail = str(underlying_error).strip()
        message = (
            "The source click was posted, but the destination click was not completed."
        )
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)
        self.move = move
        self.detection = detection
        self.source_event = source_event
        self.reason = reason
        self.underlying_error = underlying_error

    @property
    def is_cancelled(self) -> bool:
        return self.reason is MoveExecutionReason.CANCELLED


@dataclass(frozen=True, slots=True)
class MoveExecutionResult:
    move: ChessMove
    detection: BoardDetection
    source_event: PostedEvent
    destination_event: PostedEvent


@dataclass(frozen=True, slots=True)
class MoveExecutorPolicy:
    minimum_board_confidence: float = 0.85
    required_stable_detections: int = 2
    maximum_detection_age: float = 0.5
    click_delay: float = 0.15
    activation_timeout: float = 3.0
    window_tolerance: float = 1.0
    # Where to aim inside a square, as a fraction of its depth measured from
    # the far edge. A piece standing on the rank in front covers the near part
    # of the square, so the centre is not always clickable; the first depth
    # that Accessibility resolves to the intended square wins.
    aim_depths: tuple[float, ...] = (0.50, 0.34, 0.22)

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_board_confidence <= 1:
            raise ValueError("minimum board confidence must be within 0...1")
        if self.required_stable_detections < 1:
            raise ValueError("at least one stable detection is required")
        if self.maximum_detection_age < 0 or self.click_delay < 0:
            raise ValueError("timings cannot be negative")
        if self.activation_timeout <= 0 or self.window_tolerance < 0:
            raise ValueError(
                "activation timeout must be positive and tolerance non-negative"
            )
        if not self.aim_depths or any(not 0 < depth < 1 for depth in self.aim_depths):
            raise ValueError("aim depths must be a non-empty series within 0...1")


class ChessApplicationStatusPort(Protocol):
    is_frontmost: bool
    process_identifier: int | None


class ChessApplicationControllerPort(Protocol):
    async def activate(self, timeout: float = 3.0) -> ChessApplicationStatusPort: ...

    async def status(self) -> ChessApplicationStatusPort: ...


class ChessWindowPort(Protocol):
    window_id: int
    frame: Rect
    process_id: int


class ChessWindowLocatorPort(Protocol):
    async def locate(
        self, expected_process_id: int | None = None
    ) -> ChessWindowPort: ...


class BoardTrackerPort(Protocol):
    async def force_fresh_detection(self) -> object: ...


class BoardTrackerStatePort(Protocol):
    generation: int
    ready_detection: BoardDetection | None


class ChessGameSnapshotPort(Protocol):
    async def game_snapshot(
        self,
        process_identifier: int,
    ) -> tuple[str, Mapping[str, str]]: ...


class ChessSquareResolverPort(Protocol):
    async def square_at_point(
        self, process_identifier: int, point: Point
    ) -> str | None: ...


class ChessMovePostconditionPort(Protocol):
    async def capture(self, process_identifier: int, move: ChessMove) -> object: ...

    async def wait_until_applied(
        self,
        process_identifier: int,
        move: ChessMove,
        before: object,
    ) -> bool: ...


class ChessEventPosterPort(Protocol):
    async def click(self, point: Point, process_identifier: int) -> None: ...


ExecutionReporter = Callable[[MoveExecutionEvent], None]
DisplayContainsBoard = Callable[[Quad], bool]
Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class PreparedMove:
    """An immutable prepared move for one exact Chess baseline."""

    move: ChessMove
    detection: BoardDetection
    source: Point
    destination: Point
    process_identifier: int
    window_id: int
    window_frame: Rect
    ax_title: str
    square_snapshot: tuple[tuple[ChessSquare, str], ...]
    game_state: ChessGameState
    tracking_generation: int
    _before_state: object | None = field(repr=False, compare=False)
    _owner_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _TrackedDetection:
    detection: BoardDetection
    generation: int


@dataclass(frozen=True, slots=True)
class _GameBaseline:
    title: str
    square_snapshot: tuple[tuple[ChessSquare, str], ...]
    game_state: ChessGameState


class ChessMoveExecutor:
    def __init__(
        self,
        *,
        application_controller: ChessApplicationControllerPort,
        window_locator: ChessWindowLocatorPort,
        board_tracker: BoardTrackerPort,
        event_poster: ChessEventPosterPort,
        display_contains_board: DisplayContainsBoard,
        postcondition: ChessMovePostconditionPort,
        snapshot_probe: ChessGameSnapshotPort | None = None,
        square_resolver: ChessSquareResolverPort | None = None,
        policy: MoveExecutorPolicy | None = None,
        accessibility_trusted: Callable[[], bool] = is_accessibility_trusted,
        screen_recording_allowed: Callable[[], bool] = has_screen_recording_access,
        reporter: ExecutionReporter | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.time,
    ) -> None:
        self._application_controller = application_controller
        self._window_locator = window_locator
        self._board_tracker = board_tracker
        self._event_poster = event_poster
        self._display_contains_board = display_contains_board
        self._postcondition = postcondition
        self._snapshot_probe = snapshot_probe
        self._square_resolver = square_resolver
        self.policy = policy or MoveExecutorPolicy()
        self._accessibility_trusted = accessibility_trusted
        self._screen_recording_allowed = screen_recording_allowed
        self._reporter = reporter or (lambda event: None)
        self._sleep = sleep
        self._clock = clock
        self._is_executing = False
        self._pending_owner_token: object | None = None

    async def prepare(self, move: ChessMove) -> PreparedMove:
        self._begin_transaction()
        try:
            return await self._prepare(move)
        finally:
            self._is_executing = False

    async def execute_prepared(self, prepared: PreparedMove) -> MoveExecutionResult:
        self._consume_prepared(prepared)
        self._begin_transaction()
        try:
            await self._revalidate_prepared(prepared)
            return await self._execute_prepared(prepared)
        finally:
            self._is_executing = False

    def _begin_transaction(self) -> None:
        if self._is_executing:
            raise MoveExecutionBlocked(MoveExecutionReason.ALREADY_EXECUTING)
        self._is_executing = True

    def _consume_prepared(self, prepared: PreparedMove) -> None:
        if not isinstance(prepared, PreparedMove):
            raise MoveExecutionBlocked(MoveExecutionReason.INVALID_PREPARED_MOVE)
        pending_token = self._pending_owner_token
        if pending_token is None or prepared._owner_token is not pending_token:
            raise MoveExecutionBlocked(MoveExecutionReason.INVALID_PREPARED_MOVE)
        if self._is_executing:
            raise MoveExecutionBlocked(MoveExecutionReason.ALREADY_EXECUTING)
        self._pending_owner_token = None

    async def _prepare(self, move: ChessMove) -> PreparedMove:
        try:
            return await self._capture_prepared(move)
        except asyncio.CancelledError:
            raise
        except MoveExecutionBlocked:
            raise
        except Exception as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.FAILED,
                underlying_error=error,
            ) from error

    async def _capture_prepared(self, move: ChessMove) -> PreparedMove:
        if not self._accessibility_trusted():
            raise MoveExecutionBlocked(MoveExecutionReason.ACCESSIBILITY_DENIED)
        self._report_validation(MoveValidation.ACCESSIBILITY_PERMISSION)
        if not self._screen_recording_allowed():
            raise MoveExecutionBlocked(MoveExecutionReason.SCREEN_RECORDING_DENIED)
        self._report_validation(MoveValidation.SCREEN_RECORDING_PERMISSION)

        try:
            activation = await self._application_controller.activate(
                timeout=self.policy.activation_timeout
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.CHESS_ACTIVATION_FAILED,
                underlying_error=error,
            ) from error
        process_identifier = activation.process_identifier
        if (
            not activation.is_frontmost
            or isinstance(process_identifier, bool)
            or not isinstance(process_identifier, int)
            or process_identifier <= 0
        ):
            raise MoveExecutionBlocked(MoveExecutionReason.CHESS_NOT_FRONTMOST)
        self._report_validation(MoveValidation.CHESS_ACTIVATED)

        initial_window = await self._locate_window(process_identifier)
        self._report_validation(MoveValidation.INITIAL_WINDOW_SELECTED)
        self._raise_if_cancelled()

        tracked = await self._fresh_stable_detection()
        detection = tracked.detection
        self._report_validation(MoveValidation.BOARD_FRESH_AND_STABLE)
        self._raise_if_cancelled()
        if detection.source_window_id != initial_window.window_id:
            raise MoveExecutionBlocked(MoveExecutionReason.WRONG_WINDOW)
        self._report_validation(MoveValidation.BOARD_MATCHES_WINDOW)

        source, destination = await self._validated_points(
            move, detection, initial_window.frame, process_identifier
        )
        self._report_validation(MoveValidation.SQUARE_GEOMETRY)
        self._report_validation(MoveValidation.POINTS_INSIDE_WINDOW)
        self._report_validation(MoveValidation.BOARD_WITHIN_SINGLE_DISPLAY)
        self._report_validation(MoveValidation.CLICK_TARGETS_RESOLVED)

        status = await self._application_controller.status()
        if not self._same_frontmost_process(status, process_identifier):
            raise MoveExecutionBlocked(MoveExecutionReason.CHESS_NOT_FRONTMOST)
        self._report_validation(MoveValidation.CHESS_FOCUSED_BEFORE_SOURCE)
        current_window = await self._locate_window(process_identifier)
        if not self._same_window(initial_window, current_window):
            raise MoveExecutionBlocked(MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE)
        self._report_validation(MoveValidation.WINDOW_REVALIDATED_BEFORE_SOURCE)
        status = await self._application_controller.status()
        if not self._same_frontmost_process(status, process_identifier):
            raise MoveExecutionBlocked(MoveExecutionReason.CHESS_NOT_FRONTMOST)
        self._raise_if_cancelled()

        baseline = await self._capture_game_baseline(process_identifier)
        before_state = await self._capture_postcondition(process_identifier, move)
        self._raise_if_cancelled()

        owner_token = object()
        self._pending_owner_token = owner_token
        return PreparedMove(
            move=move,
            detection=detection,
            source=source,
            destination=destination,
            process_identifier=process_identifier,
            window_id=current_window.window_id,
            window_frame=current_window.frame,
            ax_title=baseline.title,
            square_snapshot=baseline.square_snapshot,
            game_state=baseline.game_state,
            tracking_generation=tracked.generation,
            _before_state=before_state,
            _owner_token=owner_token,
        )

    async def _revalidate_prepared(self, prepared: PreparedMove) -> None:
        try:
            if not self._accessibility_trusted():
                raise MoveExecutionBlocked(MoveExecutionReason.ACCESSIBILITY_DENIED)
            if not self._screen_recording_allowed():
                raise MoveExecutionBlocked(MoveExecutionReason.SCREEN_RECORDING_DENIED)

            status = await self._application_controller.status()
            if not self._same_frontmost_process(status, prepared.process_identifier):
                raise MoveExecutionBlocked(MoveExecutionReason.CHESS_NOT_FRONTMOST)

            tracked = await self._fresh_stable_detection()
            baseline = await self._capture_game_baseline(prepared.process_identifier)
            current_window = await self._locate_window(prepared.process_identifier)
            self._raise_if_cancelled()

            status = await self._application_controller.status()
            if not self._same_frontmost_process(status, prepared.process_identifier):
                raise MoveExecutionBlocked(MoveExecutionReason.CHESS_NOT_FRONTMOST)
            if not self._window_matches_prepared(prepared, current_window, exact=True):
                raise MoveExecutionBlocked(
                    MoveExecutionReason.WINDOW_CHANGED_BEFORE_SOURCE
                )
            if tracked.detection.source_window_id != prepared.window_id:
                raise MoveExecutionBlocked(MoveExecutionReason.WRONG_WINDOW)
            if not self._detection_is_usable(tracked.detection):
                raise MoveExecutionBlocked(MoveExecutionReason.BOARD_NOT_READY)
            if (
                tracked.generation != prepared.tracking_generation
                or tracked.detection.geometry != prepared.detection.geometry
                or baseline.title != prepared.ax_title
                or baseline.square_snapshot != prepared.square_snapshot
                or baseline.game_state != prepared.game_state
            ):
                raise MoveExecutionBlocked(
                    MoveExecutionReason.PREPARED_BASELINE_CHANGED
                )
            await self._validated_points(
                prepared.move,
                tracked.detection,
                current_window.frame,
                prepared.process_identifier,
                expected=(prepared.source, prepared.destination),
            )
            self._raise_if_cancelled()
            self._report_validation(
                MoveValidation.CHESS_FOCUSED_IMMEDIATELY_BEFORE_SOURCE
            )
        except asyncio.CancelledError:
            raise
        except MoveExecutionBlocked:
            raise
        except Exception as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.FAILED,
                underlying_error=error,
            ) from error

    async def _execute_prepared(self, prepared: PreparedMove) -> MoveExecutionResult:
        move = prepared.move
        try:
            cancelled_during_source = await self._post_input_atomically(
                lambda: self._event_poster.click(
                    prepared.source,
                    prepared.process_identifier,
                ),
                task_name="voice-cua-source-click",
            )
        except Exception as error:
            from voice_chess_cua.macos.mouse import EventPairPartiallyPostedError

            if isinstance(error, EventPairPartiallyPostedError):
                source_event = PostedEvent(
                    PostedEventKind.SOURCE, move.source, prepared.source
                )
                raise PartialMoveExecution(
                    move=move,
                    detection=prepared.detection,
                    source_event=source_event,
                    reason=MoveExecutionReason.EVENT_POST_FAILED,
                    underlying_error=error,
                ) from error
            raise MoveExecutionBlocked(
                MoveExecutionReason.EVENT_POST_FAILED,
                underlying_error=error,
            ) from error

        source_event = PostedEvent(PostedEventKind.SOURCE, move.source, prepared.source)
        self._report(MoveExecutionEvent.event_posted(source_event))
        try:
            if cancelled_during_source:
                raise asyncio.CancelledError
            self._raise_if_cancelled()
            await self._sleep(self.policy.click_delay)
            self._raise_if_cancelled()
            await self._revalidate_after_source(prepared)
            try:
                await self._post_input_atomically(
                    lambda: self._event_poster.click(
                        prepared.destination,
                        prepared.process_identifier,
                    ),
                    task_name="voice-cua-destination-click",
                )
            except Exception as error:
                raise MoveExecutionBlocked(
                    MoveExecutionReason.EVENT_POST_FAILED,
                    underlying_error=error,
                ) from error
            destination_event = PostedEvent(
                PostedEventKind.DESTINATION,
                move.destination,
                prepared.destination,
            )
            self._report(MoveExecutionEvent.event_posted(destination_event))
            confirmed = await self._postcondition.wait_until_applied(
                prepared.process_identifier,
                move,
                prepared._before_state,
            )
            if not confirmed:
                raise MoveExecutionUnconfirmed(
                    move=move,
                    detection=prepared.detection,
                    source_event=source_event,
                    destination_event=destination_event,
                )
            self._report_validation(MoveValidation.MOVE_CONFIRMED)
            return MoveExecutionResult(
                move=move,
                detection=prepared.detection,
                source_event=source_event,
                destination_event=destination_event,
            )
        except asyncio.CancelledError as error:
            raise PartialMoveExecution(
                move=move,
                detection=prepared.detection,
                source_event=source_event,
                reason=MoveExecutionReason.CANCELLED,
                underlying_error=error,
            ) from error
        except MoveExecutionUnconfirmed:
            raise
        except Exception as error:
            reason = (
                error.reason
                if isinstance(error, MoveExecutionBlocked)
                else MoveExecutionReason.FAILED
            )
            raise PartialMoveExecution(
                move=move,
                detection=prepared.detection,
                source_event=source_event,
                reason=reason,
                underlying_error=error,
            ) from error

    async def _revalidate_after_source(self, prepared: PreparedMove) -> None:
        status = await self._application_controller.status()
        if not self._same_frontmost_process(status, prepared.process_identifier):
            raise MoveExecutionBlocked(
                MoveExecutionReason.CHESS_LOST_FOCUS_AFTER_SOURCE
            )
        self._report_validation(MoveValidation.CHESS_FOCUSED_AFTER_SOURCE)

        current_window = await self._locate_window(prepared.process_identifier)
        self._report_validation(MoveValidation.POST_SOURCE_WINDOW_SELECTED)
        self._raise_if_cancelled()
        status = await self._application_controller.status()
        if not self._same_frontmost_process(status, prepared.process_identifier):
            raise MoveExecutionBlocked(
                MoveExecutionReason.CHESS_LOST_FOCUS_AFTER_SOURCE
            )
        self._report_validation(MoveValidation.CHESS_FOCUSED_BEFORE_DESTINATION)
        if not self._window_matches_prepared(prepared, current_window, exact=False):
            raise MoveExecutionBlocked(MoveExecutionReason.WINDOW_CHANGED_AFTER_SOURCE)
        self._report_validation(MoveValidation.WINDOW_UNCHANGED_AFTER_SOURCE)

    async def _fresh_stable_detection(self) -> _TrackedDetection:
        for attempt in range(self.policy.required_stable_detections):
            raw_state = await self._board_tracker.force_fresh_detection()
            detection = getattr(raw_state, "ready_detection", None)
            generation = getattr(raw_state, "generation", None)
            if (
                isinstance(detection, BoardDetection)
                and isinstance(generation, int)
                and not isinstance(generation, bool)
                and self._detection_is_usable(detection)
            ):
                return _TrackedDetection(detection, generation)
            if attempt + 1 < self.policy.required_stable_detections:
                await self._sleep(0.075)
        raise MoveExecutionBlocked(MoveExecutionReason.BOARD_NOT_READY)

    async def _capture_game_baseline(self, process_identifier: int) -> _GameBaseline:
        try:
            title, raw_descriptions = await self._game_snapshot_probe().game_snapshot(
                process_identifier
            )
            if not isinstance(title, str):
                raise TypeError("Apple Chess window title must be a string")
            descriptions: dict[ChessSquare, str] = {}
            for raw_square, description in raw_descriptions.items():
                if not isinstance(raw_square, str) or not isinstance(description, str):
                    raise TypeError("Apple Chess square snapshot must contain strings")
                square = ChessSquare.try_parse(raw_square)
                if square is None:
                    raise ValueError(
                        f"invalid Apple Chess snapshot key: {raw_square!r}"
                    )
                if square in descriptions:
                    raise ValueError(f"duplicate Apple Chess snapshot square: {square}")
                descriptions[square] = description
            if frozenset(descriptions) != frozenset(ChessSquare.all()):
                raise ValueError("Apple Chess snapshot must contain all 64 squares")
            canonical = tuple(
                (square, descriptions[square]) for square in ChessSquare.all()
            )
            snapshot = AppleChessSnapshot(
                title,
                {
                    square.notation.lower(): description
                    for square, description in canonical
                },
            )
            return _GameBaseline(title, canonical, parse_apple_chess_snapshot(snapshot))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.BOARD_NOT_READY,
                underlying_error=error,
            ) from error

    async def _capture_postcondition(
        self,
        process_identifier: int,
        move: ChessMove,
    ) -> object:
        try:
            return await self._postcondition.capture(process_identifier, move)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.BOARD_NOT_READY,
                underlying_error=error,
            ) from error

    def _game_snapshot_probe(self) -> ChessGameSnapshotPort:
        if self._snapshot_probe is None:
            from voice_chess_cua.macos.chess_accessibility import (
                ChessBoardAccessibilityProbe,
            )

            self._snapshot_probe = ChessBoardAccessibilityProbe()
        return self._snapshot_probe

    def _square_resolver_port(self) -> ChessSquareResolverPort:
        if self._square_resolver is None:
            from voice_chess_cua.macos.chess_accessibility import (
                ChessBoardAccessibilityProbe,
            )

            self._square_resolver = ChessBoardAccessibilityProbe()
        return self._square_resolver

    async def _validated_points(
        self,
        move: ChessMove,
        detection: BoardDetection,
        window_frame: Rect,
        process_identifier: int,
        *,
        expected: tuple[Point, Point] | None = None,
    ) -> tuple[Point, Point]:
        if not self._display_contains_board(detection.geometry.quad):
            raise MoveExecutionBlocked(MoveExecutionReason.BOARD_SPANS_DISPLAYS)
        source = await self._clickable_point(
            move.source, detection, window_frame, process_identifier
        )
        destination = await self._clickable_point(
            move.destination, detection, window_frame, process_identifier
        )
        if expected is not None and (source, destination) != expected:
            raise MoveExecutionBlocked(MoveExecutionReason.PREPARED_BASELINE_CHANGED)
        return source, destination

    async def _clickable_point(
        self,
        square: ChessSquare,
        detection: BoardDetection,
        window_frame: Rect,
        process_identifier: int,
    ) -> Point:
        resolver = self._square_resolver_port()
        notation = square.notation.lower()
        for depth in self.policy.aim_depths:
            point = self._geometric_point(square, detection, window_frame, depth)
            self._raise_if_cancelled()
            try:
                resolved = await resolver.square_at_point(process_identifier, point)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise MoveExecutionBlocked(
                    MoveExecutionReason.SQUARE_NOT_CLICKABLE,
                    underlying_error=error,
                ) from error
            if resolved == notation:
                return point
        raise MoveExecutionBlocked(MoveExecutionReason.SQUARE_NOT_CLICKABLE)

    def _geometric_point(
        self,
        square: ChessSquare,
        detection: BoardDetection,
        window_frame: Rect,
        depth: float,
    ) -> Point:
        try:
            point = detection.geometry.aim_point(square, depth)
            is_inside = detection.geometry.contains(point)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.INVALID_SQUARE_GEOMETRY,
                underlying_error=error,
            ) from error
        if not point.is_finite or not is_inside:
            raise MoveExecutionBlocked(MoveExecutionReason.INVALID_SQUARE_GEOMETRY)
        if not window_frame.contains(point):
            raise MoveExecutionBlocked(MoveExecutionReason.POINT_OUTSIDE_WINDOW)
        return point

    def _window_matches_prepared(
        self,
        prepared: PreparedMove,
        current: ChessWindowPort,
        *,
        exact: bool,
    ) -> bool:
        if (
            current.process_id != prepared.process_identifier
            or current.window_id != prepared.window_id
        ):
            return False
        if exact:
            return current.frame == prepared.window_frame
        return self._rects_approximately_equal(
            current.frame,
            prepared.window_frame,
            tolerance=self.policy.window_tolerance,
        )

    def _detection_is_usable(self, detection: BoardDetection) -> bool:
        captured_at = detection.captured_at
        timestamp = (
            captured_at.timestamp()
            if hasattr(captured_at, "timestamp")
            else float(captured_at)
        )
        age = self._clock() - timestamp
        return (
            detection.confidence >= self.policy.minimum_board_confidence
            and 0 <= age <= self.policy.maximum_detection_age
        )

    async def _locate_window(self, process_identifier: int) -> ChessWindowPort:
        try:
            window = await self._window_locator.locate(
                expected_process_id=process_identifier
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MoveExecutionBlocked(
                MoveExecutionReason.WINDOW_SELECTION_FAILED,
                underlying_error=error,
            ) from error
        if window.process_id != process_identifier:
            raise MoveExecutionBlocked(MoveExecutionReason.WINDOW_SELECTION_FAILED)
        return window

    def _same_window(self, initial: ChessWindowPort, current: ChessWindowPort) -> bool:
        return (
            current.process_id == initial.process_id
            and current.window_id == initial.window_id
            and self._rects_approximately_equal(
                current.frame,
                initial.frame,
                tolerance=self.policy.window_tolerance,
            )
        )

    @staticmethod
    def _same_frontmost_process(
        status: ChessApplicationStatusPort,
        process_identifier: int,
    ) -> bool:
        return status.is_frontmost and status.process_identifier == process_identifier

    @staticmethod
    def _rects_approximately_equal(
        left: Rect, right: Rect, *, tolerance: float
    ) -> bool:
        return all(
            abs(left_value - right_value) <= tolerance
            for left_value, right_value in zip(
                (left.x, left.y, left.width, left.height),
                (right.x, right.y, right.width, right.height),
                strict=True,
            )
        )

    async def _post_input_atomically(
        self,
        operation: Callable[[], Awaitable[None]],
        *,
        task_name: str,
    ) -> bool:
        post_task: asyncio.Future[None] = asyncio.ensure_future(operation())
        if isinstance(post_task, asyncio.Task):
            post_task.set_name(task_name)
        was_cancelled = False
        while not post_task.done():
            try:
                await asyncio.shield(post_task)
            except asyncio.CancelledError:
                was_cancelled = True
        await post_task
        return was_cancelled

    @staticmethod
    def _raise_if_cancelled() -> None:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError

    def _report_validation(self, validation: MoveValidation) -> None:
        self._report(MoveExecutionEvent.validation_passed(validation))

    def _report(self, event: MoveExecutionEvent) -> None:
        try:
            self._reporter(event)
        except Exception:  # noqa: BLE001 - telemetry must never affect input safety
            return
