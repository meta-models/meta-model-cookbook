# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Generation-safe asynchronous board tracking."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from voice_chess_cua.domain.geometry import BoardDetection
from voice_chess_cua.runtime.ports import (
    TrackingFailureReason,
    TrackingStatus,
    TrackingUpdate,
)

DetectionOperation = Callable[[], Awaitable[BoardDetection | None]]
StateCallback = Callable[["BoardTrackingState"], None]


class BoardDetectionError(RuntimeError):
    def __init__(self, reason: TrackingFailureReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True, slots=True)
class BoardTrackingPolicy:
    cadence: float = 0.25
    minimum_confidence: float = 0.85
    required_stable_detections: int = 2
    maximum_detection_age: float = 0.5
    maximum_corner_drift_fraction: float = 0.01

    def __post_init__(self) -> None:
        if self.cadence < 0:
            raise ValueError("tracking cadence cannot be negative")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum confidence must be within 0...1")
        if self.required_stable_detections < 1:
            raise ValueError("at least one stable detection is required")
        if self.maximum_detection_age < 0:
            raise ValueError("maximum detection age cannot be negative")
        if self.maximum_corner_drift_fraction < 0:
            raise ValueError("maximum corner drift cannot be negative")


@dataclass(frozen=True, slots=True)
class BoardTrackingState:
    status: TrackingStatus
    generation: int
    latest_detection: BoardDetection | None = None
    stable_detection: BoardDetection | None = None
    stable_count: int = 0
    is_fresh: bool = False
    failure_reason: TrackingFailureReason | None = None

    @property
    def ready_detection(self) -> BoardDetection | None:
        if self.status is TrackingStatus.STABLE and self.is_fresh:
            return self.stable_detection
        return None

    def as_update(self) -> TrackingUpdate:
        return TrackingUpdate(
            status=self.status,
            generation=self.generation,
            detection=self.ready_detection,
            failure_reason=self.failure_reason,
        )


class BoardTrackingService:
    """Tracks stable detections and rejects completions from superseded runs."""

    def __init__(
        self,
        detection_operation: DetectionOperation,
        *,
        policy: BoardTrackingPolicy | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy or BoardTrackingPolicy()
        self._detection_operation = detection_operation
        self._clock = clock
        self._state = BoardTrackingState(TrackingStatus.IDLE, generation=0)
        self._generation = 0
        self._run_id = 0
        self._next_detection_request = 0
        self._latest_applied_request = 0
        self._cadence_task: asyncio.Task[None] | None = None
        self._retired_tasks: set[asyncio.Task[None]] = set()
        self._callback: StateCallback | None = None
        self._subscribers: set[asyncio.Queue[TrackingUpdate]] = set()

    async def start(self, *, generation: int) -> None:
        current = self._cadence_task
        if (
            current is not None
            and not current.done()
            and self._generation == generation
        ):
            return
        if current is not None and not current.done():
            current.cancel()
            self._retire(current)

        self._run_id += 1
        run_id = self._run_id
        self._generation = generation
        self._publish(
            BoardTrackingState(
                status=TrackingStatus.SEARCHING,
                generation=generation,
                latest_detection=self._state.latest_detection,
                failure_reason=self._state.failure_reason,
            )
        )
        task = asyncio.create_task(
            self._run_cadence(run_id, generation),
            name=f"voice-cua-board-tracking-{generation}",
        )
        self._cadence_task = task

    async def stop(self) -> None:
        self._run_id += 1
        stop_run_id = self._run_id
        current_task = asyncio.current_task()
        active = self._cadence_task
        self._cadence_task = None

        tasks = set(self._retired_tasks)
        if active is not None:
            tasks.add(active)
            self._retire(active)
        for task in tasks:
            if task is not current_task and not task.done():
                task.cancel()
        awaitables = tuple(task for task in tasks if task is not current_task)
        if awaitables:
            await asyncio.gather(*awaitables, return_exceptions=True)
        self._retired_tasks.difference_update(awaitables)

        if self._run_id == stop_run_id:
            self._publish(
                BoardTrackingState(
                    status=TrackingStatus.STOPPED,
                    generation=self._generation,
                    latest_detection=self._state.latest_detection,
                    failure_reason=self._state.failure_reason,
                )
            )

    def updates(self) -> AsyncIterator[TrackingUpdate]:
        return self._updates()

    async def _updates(self) -> AsyncIterator[TrackingUpdate]:
        queue: asyncio.Queue[TrackingUpdate] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        self._offer(queue, self._state.as_update())
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    def set_callback(self, callback: StateCallback | None) -> None:
        self._callback = callback
        if callback is not None:
            callback(self._state)

    async def force_fresh_detection(
        self,
        *,
        now: datetime | float | None = None,
    ) -> BoardTrackingState:
        run_id = self._run_id
        generation = self._generation
        request_id = self._begin_detection_request()
        try:
            detection = await self._detection_operation()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - detector failures become tracking state
            if self._can_apply(run_id, generation, request_id):
                self._latest_applied_request = request_id
                return self._publish_failure(error)
            return self._state
        if not self._can_apply(run_id, generation, request_id):
            return self._state
        self._latest_applied_request = request_id
        return self._ingest(detection, now=self._now(now))

    async def ingest(
        self,
        detection: BoardDetection | None,
        *,
        now: datetime | float | None = None,
        generation: int | None = None,
    ) -> BoardTrackingState:
        if generation is not None and generation != self._generation:
            return self._state
        return self._ingest(detection, now=self._now(now))

    async def current_state(
        self,
        *,
        now: datetime | float | None = None,
    ) -> BoardTrackingState:
        latest = self._state.latest_detection
        if latest is not None and not self._is_fresh(latest, self._now(now)):
            self._publish(
                BoardTrackingState(
                    status=TrackingStatus.STALE,
                    generation=self._generation,
                    latest_detection=latest,
                    failure_reason=self._state.failure_reason,
                )
            )
        return self._state

    async def _run_cadence(self, run_id: int, generation: int) -> None:
        try:
            while self._is_current(run_id, generation):
                request_id = self._begin_detection_request()
                try:
                    detection = await self._detection_operation()
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - detector failures become tracking state
                    if self._can_apply(run_id, generation, request_id):
                        self._latest_applied_request = request_id
                        self._publish_failure(error)
                else:
                    if self._can_apply(run_id, generation, request_id):
                        self._latest_applied_request = request_id
                        self._ingest(detection, now=self._clock())
                if not self._is_current(run_id, generation):
                    return
                await asyncio.sleep(self.policy.cadence)
        except asyncio.CancelledError:
            return
        finally:
            current = asyncio.current_task()
            if self._cadence_task is current:
                self._cadence_task = None

    def _ingest(
        self, detection: BoardDetection | None, *, now: float
    ) -> BoardTrackingState:
        if (
            detection is None
            or detection.confidence < self.policy.minimum_confidence
            or not self._is_fresh(detection, now)
        ):
            status = (
                TrackingStatus.SEARCHING
                if self._state.latest_detection is None
                else TrackingStatus.STALE
            )
            return self._publish(
                BoardTrackingState(
                    status=status,
                    generation=self._generation,
                    latest_detection=self._state.latest_detection,
                )
            )

        previous = self._state.latest_detection
        if previous is not None and self._timestamp(
            detection.captured_at
        ) <= self._timestamp(previous.captured_at):
            return self._state

        stable_count = 1
        if (
            previous is not None
            and previous.geometry.orientation is detection.geometry.orientation
            and previous.source_window_id == detection.source_window_id
            and self._corner_drift_fraction(previous, detection)
            <= self.policy.maximum_corner_drift_fraction
        ):
            stable_count = self._state.stable_count + 1

        stable = stable_count >= self.policy.required_stable_detections
        return self._publish(
            BoardTrackingState(
                status=TrackingStatus.STABLE if stable else TrackingStatus.ACQUIRING,
                generation=self._generation,
                latest_detection=detection,
                stable_detection=detection if stable else None,
                stable_count=stable_count,
                is_fresh=True,
            )
        )

    def _publish_failure(self, error: Exception) -> BoardTrackingState:
        reason = (
            error.reason
            if isinstance(error, BoardDetectionError)
            else TrackingFailureReason.DETECTION_FAILED
        )
        return self._publish(
            BoardTrackingState(
                status=TrackingStatus.FAILED,
                generation=self._generation,
                latest_detection=self._state.latest_detection,
                failure_reason=reason,
            )
        )

    def _publish(self, state: BoardTrackingState) -> BoardTrackingState:
        self._state = state
        if self._callback is not None:
            self._callback(state)
        update = state.as_update()
        for queue in tuple(self._subscribers):
            self._offer(queue, update)
        return state

    def _is_current(self, run_id: int, generation: int) -> bool:
        return run_id == self._run_id and generation == self._generation

    def _begin_detection_request(self) -> int:
        self._next_detection_request += 1
        return self._next_detection_request

    def _can_apply(self, run_id: int, generation: int, request_id: int) -> bool:
        return (
            self._is_current(run_id, generation)
            and request_id > self._latest_applied_request
        )

    def _retire(self, task: asyncio.Task[None]) -> None:
        self._retired_tasks.add(task)
        task.add_done_callback(self._retired_tasks.discard)

    def _is_fresh(self, detection: BoardDetection, now: float) -> bool:
        age = now - self._timestamp(detection.captured_at)
        return 0 <= age <= self.policy.maximum_detection_age

    @staticmethod
    def _timestamp(value: datetime | float) -> float:
        if isinstance(value, datetime):
            return value.timestamp()
        return float(value)

    def _now(self, value: datetime | float | None) -> float:
        if value is None:
            return self._clock()
        if isinstance(value, datetime):
            return value.timestamp()
        return float(value)

    @staticmethod
    def _corner_drift_fraction(
        previous: BoardDetection, current: BoardDetection
    ) -> float:
        quad = previous.geometry.quad
        scale = max((quad.width**2 + quad.height**2) ** 0.5, 1.0)
        return float(quad.maximum_corner_distance_to(current.geometry.quad) / scale)

    @staticmethod
    def _offer(queue: asyncio.Queue[TrackingUpdate], update: TrackingUpdate) -> None:
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(update)
