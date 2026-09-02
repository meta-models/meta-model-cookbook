# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""AVFoundation microphone capture with a bounded callback-to-asyncio handoff."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from math import isfinite
from queue import Empty, Queue
from threading import Lock
from typing import Any, Protocol, cast

from voice_chess_cua.settings import STANDARD_SAFETY_POLICY
from voice_chess_cua.voice.pcm import (
    SAMPLE_RATE,
    PCMChunker,
    StreamingLinearResampler,
    float_samples_to_pcm16le,
)


class AudioCaptureError(RuntimeError):
    pass


class AudioAlreadyRunningError(AudioCaptureError):
    pass


class AudioInvalidInputFormatError(AudioCaptureError):
    pass


class AudioBufferOverrunError(AudioCaptureError):
    pass


class AudioBackend(Protocol):
    def start(self, callback: Callable[[object], None]) -> None: ...

    def stop(self) -> None: ...

    def decode(self, buffer: object) -> tuple[Sequence[float], float]: ...

    def duration(self, buffer: object) -> float: ...


class _AVFoundationAudioBackend:
    def __init__(self) -> None:
        from .native import load_framework

        self._av_foundation = load_framework("AVFoundation")
        self._engine: Any | None = None
        self._input_node: Any | None = None
        self._tap_handler: object | None = None

    def start(self, callback: Callable[[object], None]) -> None:
        engine = self._av_foundation.AVAudioEngine.alloc().init()
        input_node = engine.inputNode()
        input_format = input_node.outputFormatForBus_(0)
        sample_rate = float(input_format.sampleRate())
        channel_count = int(input_format.channelCount())
        if sample_rate <= 0 or channel_count <= 0:
            raise AudioInvalidInputFormatError(
                "The microphone input format is invalid."
            )

        def tap_handler(buffer: object, _time: object) -> None:
            callback(buffer)

        input_node.installTapOnBus_bufferSize_format_block_(
            0,
            1_024,
            input_format,
            tap_handler,
        )
        engine.prepare()
        started, error = engine.startAndReturnError_(None)
        if not started:
            input_node.removeTapOnBus_(0)
            raise AudioCaptureError(str(error or "AVAudioEngine failed to start"))
        self._engine = engine
        self._input_node = input_node
        self._tap_handler = tap_handler

    def stop(self) -> None:
        if self._input_node is not None:
            self._input_node.removeTapOnBus_(0)
        if self._engine is not None:
            self._engine.stop()
        self._tap_handler = None
        self._input_node = None
        self._engine = None

    def duration(self, buffer: object) -> float:
        frame_length = int(buffer.frameLength())  # type: ignore[attr-defined]
        sample_rate = float(buffer.format().sampleRate())  # type: ignore[attr-defined]
        if frame_length < 0 or not isfinite(sample_rate) or sample_rate <= 0:
            raise AudioInvalidInputFormatError(
                "AVFoundation returned an invalid audio buffer."
            )
        return frame_length / sample_rate

    def decode(self, buffer: object) -> tuple[Sequence[float], float]:
        frame_length = int(buffer.frameLength())  # type: ignore[attr-defined]
        format_ = buffer.format()  # type: ignore[attr-defined]
        sample_rate = float(format_.sampleRate())
        channel_count = int(format_.channelCount())
        channels = buffer.floatChannelData()  # type: ignore[attr-defined]
        if (
            frame_length < 0
            or sample_rate <= 0
            or channel_count <= 0
            or channels is None
        ):
            raise AudioInvalidInputFormatError(
                "AVFoundation returned an invalid audio buffer."
            )
        if channel_count == 1:
            return tuple(
                float(channels[0][index]) for index in range(frame_length)
            ), sample_rate
        return (
            tuple(
                sum(float(channels[channel][index]) for channel in range(channel_count))
                / channel_count
                for index in range(frame_length)
            ),
            sample_rate,
        )


_STOP = object()


@dataclass(frozen=True, slots=True)
class _QueuedAudio:
    buffer: object
    duration: float


@dataclass(slots=True)
class _CaptureGeneration:
    identifier: int
    queue: Queue[_QueuedAudio | object] = field(default_factory=Queue)
    chunker: PCMChunker = field(default_factory=PCMChunker)
    resampler: StreamingLinearResampler | None = None
    source_rate: float | None = None
    queued_duration: float = 0.0
    failure: BaseException | None = None
    stop_enqueued: bool = False
    completed: asyncio.Event = field(default_factory=asyncio.Event)


class AudioCaptureService:
    """Produces mono PCM16 24 kHz frames without doing work in the native callback."""

    def __init__(
        self,
        backend: AudioBackend | None = None,
        *,
        maximum_buffered_duration: float = (
            STANDARD_SAFETY_POLICY.maximum_buffered_audio_duration_seconds
        ),
    ) -> None:
        if maximum_buffered_duration <= 0:
            raise ValueError("maximum buffered duration must be positive")
        self._backend = backend
        self._maximum_buffered_duration = maximum_buffered_duration
        self._generation = 0
        self._state: _CaptureGeneration | None = None
        self._running = False
        self._transaction_busy = False
        self._lock = Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._start_task: asyncio.Task[None] | None = None

    @property
    def backend(self) -> AudioBackend:
        if self._backend is None:
            self._backend = _AVFoundationAudioBackend()
        return self._backend

    def set_transaction_busy(self, busy: bool) -> None:
        if not isinstance(busy, bool):
            raise TypeError("transaction busy state must be a boolean")
        with self._lock:
            self._transaction_busy = busy

    async def start(self) -> None:
        async with self._lifecycle_lock:
            with self._lock:
                if self._running or self._start_task is not None:
                    raise AudioAlreadyRunningError("Audio capture is already running.")
                self._generation += 1
                state = _CaptureGeneration(self._generation)
                self._state = state
                self._running = True
            start_task = asyncio.create_task(
                asyncio.to_thread(
                    self.backend.start,
                    lambda buffer: self._receive_buffer(state, buffer),
                )
            )
            self._start_task = start_task
            try:
                await asyncio.shield(start_task)
            except BaseException:
                await self._finish_cancelled_start(start_task, state)
                raise
            finally:
                self._start_task = None

    def frames(self) -> AsyncIterator[bytes]:
        with self._lock:
            state = self._state

        async def iterate() -> AsyncIterator[bytes]:
            if state is None:
                raise AudioCaptureError("Audio capture has not been started.")
            async for frame in self._frames(state):
                yield frame

        return iterate()

    async def _frames(self, state: _CaptureGeneration) -> AsyncIterator[bytes]:
        try:
            while True:
                queued = await asyncio.to_thread(state.queue.get)
                if queued is _STOP:
                    failure = state.failure
                    if failure is not None:
                        self._clear_processing_state(state)
                        raise failure
                    for chunk in self._finish_pcm(state):
                        yield chunk
                    return
                item = cast(_QueuedAudio, queued)
                with self._lock:
                    state.queued_duration = max(
                        0.0, state.queued_duration - item.duration
                    )
                samples, source_rate = await asyncio.to_thread(
                    self.backend.decode, item.buffer
                )
                if state.resampler is None or state.source_rate != source_rate:
                    if state.resampler is not None:
                        for chunk in state.chunker.append(
                            float_samples_to_pcm16le(state.resampler.finish())
                        ):
                            yield chunk
                    state.resampler = StreamingLinearResampler(source_rate, SAMPLE_RATE)
                    state.source_rate = source_rate
                resampled = state.resampler.append(samples)
                for chunk in state.chunker.append(float_samples_to_pcm16le(resampled)):
                    yield chunk
        finally:
            self._retire_state(state)
            state.completed.set()

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            start_task = self._start_task
            if start_task is not None:
                await asyncio.shield(start_task)
            with self._lock:
                state = self._state
                was_running = self._running
                self._running = False
            if was_running:
                await asyncio.to_thread(self.backend.stop)
            if state is not None:
                self._enqueue_stop(state)

    async def drain(self) -> None:
        with self._lock:
            state = self._state
        if state is None:
            return
        if not state.stop_enqueued:
            raise AudioCaptureError(
                "Audio capture must be stopped before it can be drained."
            )
        await state.completed.wait()

    async def _finish_cancelled_start(
        self,
        start_task: asyncio.Task[None],
        state: _CaptureGeneration,
    ) -> None:
        try:
            await asyncio.shield(start_task)
        except Exception as error:  # noqa: BLE001 - cleanup must still stop the backend.
            state.failure = error
        with self._lock:
            if self._state is state:
                self._running = False
        await asyncio.to_thread(self.backend.stop)
        self._enqueue_stop(state)

    def _receive_buffer(self, state: _CaptureGeneration, buffer: object) -> None:
        with self._lock:
            if (
                not self._running
                or self._state is not state
                or state.failure is not None
                or self._transaction_busy
            ):
                return
            try:
                duration = self.backend.duration(buffer)
            except Exception as error:  # noqa: BLE001 - native callback reports fatal failure.
                state.failure = error
                self._discard_queued_buffers_locked(state)
                self._enqueue_stop_locked(state)
                return
            if state.queued_duration + duration > self._maximum_buffered_duration:
                state.failure = AudioBufferOverrunError(
                    "Microphone capture exceeded the bounded audio buffer."
                )
                self._discard_queued_buffers_locked(state)
                self._enqueue_stop_locked(state)
                return
            state.queued_duration += duration
            # Queue insertion under the capture lock prevents stop overtaking accepted audio.
            state.queue.put_nowait(_QueuedAudio(buffer, duration))

    def _finish_pcm(self, state: _CaptureGeneration) -> list[bytes]:
        chunks: list[bytes] = []
        if state.resampler is not None:
            chunks.extend(
                state.chunker.append(float_samples_to_pcm16le(state.resampler.finish()))
            )
        state.resampler = None
        state.source_rate = None
        tail = state.chunker.finish()
        if len(tail) % 2:
            raise AudioCaptureError(
                "PCM16 tail must contain complete two-byte samples."
            )
        if tail:
            chunks.append(tail)
        return chunks

    def _clear_processing_state(self, state: _CaptureGeneration) -> None:
        with self._lock:
            state.queued_duration = 0.0
        state.chunker.clear()
        if state.resampler is not None:
            state.resampler.clear()
        state.resampler = None
        state.source_rate = None

    def _discard_queued_buffers(
        self,
        state: _CaptureGeneration,
        *,
        preserve_stop: bool = False,
    ) -> None:
        with self._lock:
            self._discard_queued_buffers_locked(state, preserve_stop=preserve_stop)

    def _retire_state(self, state: _CaptureGeneration) -> None:
        with self._lock:
            state.queued_duration = 0.0
            if self._state is state and not self._running:
                self._state = None

    @staticmethod
    def _discard_queued_buffers_locked(
        state: _CaptureGeneration,
        *,
        preserve_stop: bool = False,
    ) -> None:
        saw_stop = False
        while True:
            try:
                queued = state.queue.get_nowait()
            except Empty:
                state.queued_duration = 0.0
                if preserve_stop and (saw_stop or state.stop_enqueued):
                    state.queue.put_nowait(_STOP)
                return
            saw_stop = saw_stop or queued is _STOP

    def _enqueue_stop(self, state: _CaptureGeneration) -> None:
        with self._lock:
            self._enqueue_stop_locked(state)

    @staticmethod
    def _enqueue_stop_locked(state: _CaptureGeneration) -> None:
        if state.stop_enqueued:
            return
        state.stop_enqueued = True
        state.queue.put_nowait(_STOP)
