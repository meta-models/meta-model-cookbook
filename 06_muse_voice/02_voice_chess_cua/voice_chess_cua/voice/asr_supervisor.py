# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Long-lived supervision for public endpointing ASR sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, cast

from voice_chess_cua.runtime.ports import (
    FinalTranscript,
    PartialTranscript,
    SpeechStarted,
    SupervisedFinalTranscript,
    VoiceEvent,
    VoiceLifecycle,
    VoiceLifecycleEvent,
    VoiceWorkerFailure,
)
from voice_chess_cua.voice.asr_client import (
    ASRConnectionClosedError,
    ASRServerReportedError,
    ASRTransportError,
    VoiceASRClient,
)

_DEFAULT_DRAIN_TIMEOUT = 6.0
_DEFAULT_RECONNECT_TIMEOUT = 6.0
_DEFAULT_EVENT_BUFFER_SIZE = 256
_DEFAULT_SESSION_LIFETIME = 9.5 * 60.0
_DEFAULT_MAX_RECONNECT_ATTEMPTS = 3
_DEFAULT_RECONNECT_BACKOFF = (0.0, 0.25, 1.0)
_EVENT_STREAM_END = object()


class ASRSession(Protocol):
    async def connect(self, *, settings: object, access_token: str) -> None: ...

    def events(self) -> AsyncIterator[VoiceEvent]: ...

    async def send_audio(self, frame: bytes) -> None: ...

    async def end_stream(self) -> None: ...

    async def wait_closed(self, timeout: float) -> bool: ...

    async def disconnect(self) -> None: ...


ASRSessionFactory = Callable[[], ASRSession]


class ASRSupervisorError(RuntimeError):
    """Base error for failures introduced by the session supervisor."""


class ASREventStreamEndedError(ASRSupervisorError):
    """Raised when an active raw ASR event stream ends unexpectedly."""


class AlreadyConnectedSupervisorError(ASRSupervisorError):
    """Raised when connect is called while the supervisor is already running."""


class ASREventBufferOverflowError(ASRSupervisorError):
    """Raised instead of retaining unbounded authoritative voice events."""


class _State(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    ACTIVE = "active"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    STOPPING = "stopping"
    CLOSED = "closed"


@dataclass(slots=True)
class _Session:
    generation: int
    client: ASRSession
    iterator: AsyncIterator[VoiceEvent] | None = None
    pump_task: asyncio.Task[None] | None = None
    stream_done: asyncio.Event = field(default_factory=asyncio.Event)
    close_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    latest_turn_id: str | None = None
    forwarding: bool = True
    closed: bool = False
    cleanup_failed: bool = False


class ASRSupervisor:
    """Expose one stable event stream across bounded ASR session replacements.

    Server endpointing owns turn boundaries. A raw connection stays open across turns
    and is replaced only before its service lifetime or after a retryable transport
    failure. Audio arriving during replacement is dropped and is never replayed.
    """

    def __init__(
        self,
        client: ASRSession | None = None,
        *,
        client_factory: ASRSessionFactory | None = None,
        drain_timeout: float = _DEFAULT_DRAIN_TIMEOUT,
        reconnect_timeout: float = _DEFAULT_RECONNECT_TIMEOUT,
        session_lifetime: float = _DEFAULT_SESSION_LIFETIME,
        max_reconnect_attempts: int = _DEFAULT_MAX_RECONNECT_ATTEMPTS,
        reconnect_backoff: tuple[float, ...] = _DEFAULT_RECONNECT_BACKOFF,
        event_buffer_size: int = _DEFAULT_EVENT_BUFFER_SIZE,
    ) -> None:
        if client is not None and client_factory is not None:
            raise ValueError("provide either client or client_factory, not both")
        if drain_timeout < 0:
            raise ValueError("drain_timeout must not be negative")
        if reconnect_timeout <= 0:
            raise ValueError("reconnect_timeout must be positive")
        if session_lifetime <= 0 or session_lifetime >= 10 * 60:
            raise ValueError(
                "session_lifetime must be positive and less than ten minutes"
            )
        if isinstance(max_reconnect_attempts, bool) or not isinstance(
            max_reconnect_attempts, int
        ):
            raise TypeError("max_reconnect_attempts must be an integer")
        if max_reconnect_attempts <= 0:
            raise ValueError("max_reconnect_attempts must be positive")
        if len(reconnect_backoff) < max_reconnect_attempts:
            raise ValueError("reconnect_backoff must cover every reconnect attempt")
        if any(delay < 0 for delay in reconnect_backoff):
            raise ValueError("reconnect backoff delays must not be negative")
        if isinstance(event_buffer_size, bool) or not isinstance(
            event_buffer_size, int
        ):
            raise TypeError("event_buffer_size must be an integer")
        if event_buffer_size <= 0:
            raise ValueError("event_buffer_size must be positive")

        if client is not None:
            self._client_factory: ASRSessionFactory = lambda: client
        else:
            self._client_factory = client_factory or _default_client_factory
        self._drain_timeout = drain_timeout
        self._reconnect_timeout = reconnect_timeout
        self._session_lifetime = session_lifetime
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_backoff = reconnect_backoff
        self._event_buffer_size = event_buffer_size

        self._state = _State.IDLE
        self._generation = 0
        self._settings: object | None = None
        self._meta_api_key: str | None = None
        self._session: _Session | None = None
        self._pending_session: _Session | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._lifetime_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._audio_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._events: asyncio.Queue[VoiceEvent | object] = asyncio.Queue(
            maxsize=event_buffer_size + 2
        )
        self._events_finished = False
        self._closed = asyncio.Event()
        self._closed.set()
        self._terminal = False

    @property
    def generation(self) -> int:
        return self._generation

    async def connect(self, *, settings: object, access_token: str) -> None:
        async with self._connect_lock:
            if self._state not in {_State.IDLE, _State.CLOSED}:
                raise AlreadyConnectedSupervisorError(
                    "The ASR supervisor is already connected."
                )

            self._reset_event_stream()
            self._closed.clear()
            self._terminal = False
            self._state = _State.CONNECTING
            self._settings = settings
            self._meta_api_key = access_token

            current_task = asyncio.current_task()
            assert current_task is not None
            self._connect_task = current_task
            session: _Session | None = None
            try:
                session = _Session(self._generation + 1, self._client_factory())
                self._pending_session = session
                await asyncio.wait_for(
                    session.client.connect(
                        settings=settings, access_token=access_token
                    ),
                    timeout=self._reconnect_timeout,
                )
                if self._terminal:
                    await self._close_session(session)
                    self._state = _State.CLOSED
                    self._closed.set()
                    self._finish_event_stream()
                    return
                self._pending_session = None
                self._install_session(session)
            except BaseException:
                if session is not None:
                    with suppress(BaseException):
                        await self._close_session(session)
                self._clear_credentials()
                self._state = _State.CLOSED
                self._closed.set()
                self._finish_event_stream()
                raise
            finally:
                if self._pending_session is session:
                    self._pending_session = None
                if self._connect_task is current_task:
                    self._connect_task = None

    def events(self) -> AsyncIterator[VoiceEvent]:
        queue = self._events

        async def iterate() -> AsyncIterator[VoiceEvent]:
            while True:
                item = await queue.get()
                if item is _EVENT_STREAM_END:
                    return
                yield cast(VoiceEvent, item)

        return iterate()

    async def send_audio(self, frame: bytes) -> None:
        if self._terminal or self._state is not _State.ACTIVE:
            return
        async with self._audio_lock:
            session = self._session
            if self._terminal or self._state is not _State.ACTIVE or session is None:
                return
            try:
                await session.client.send_audio(frame)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - ASR adapters define failures.
                if self._is_retryable(error):
                    self._begin_reconnect_locked(session, error)
                else:
                    self._fail_session_locked(session, error)

    async def end_stream(self) -> None:
        async with self._audio_lock:
            self._terminal = True
            previous_state = self._state
            self._state = _State.STOPPING
            lifetime_task = self._lifetime_task
            reconnect_task = self._reconnect_task
            connect_task = self._connect_task
            session = self._session
            pending_session = self._pending_session
            self._lifetime_task = None

        await self._cancel_tasks(lifetime_task, reconnect_task, connect_task)
        if previous_state in {_State.CONNECTING, _State.RECONNECTING}:
            for candidate in self._unique_sessions(session, pending_session):
                await self._close_session(candidate)
            self._session = None
            self._pending_session = None
            self._clear_credentials()
            self._state = _State.CLOSED
            self._closed.set()
            self._finish_event_stream()
            return
        if session is None:
            self._state = _State.CLOSED
            self._closed.set()
            self._finish_event_stream()
            return
        try:
            await asyncio.wait_for(
                session.client.end_stream(), timeout=self._drain_timeout
            )
        except TimeoutError:
            await self._close_session(session)
            self._closed.set()
            self._finish_event_stream()
        except asyncio.CancelledError:
            raise
        except Exception as end_stream_error:
            try:
                await self._close_session(session)
            except Exception as cleanup_error:
                raise cleanup_error from end_stream_error
            self._closed.set()
            self._finish_event_stream()
            raise

    async def wait_closed(self, timeout: float) -> bool:
        if self._closed.is_set():
            return True
        session = self._session
        if self._terminal and session is not None:
            if session.cleanup_failed:
                return False
            loop = asyncio.get_running_loop()
            deadline = loop.time() + max(0.0, timeout)
            if not await session.client.wait_closed(max(0.0, timeout)):
                return False
            if not session.stream_done.is_set():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return False
                try:
                    await asyncio.wait_for(
                        session.stream_done.wait(), timeout=remaining
                    )
                except TimeoutError:
                    return False
            self._closed.set()
            self._finish_event_stream()
            return True
        if timeout <= 0:
            return False
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def disconnect(self) -> None:
        async with self._audio_lock:
            self._terminal = True
            previous_state = self._state
            self._state = _State.STOPPING
            active_session = self._session
            pending_session = self._pending_session
            for session in self._unique_sessions(active_session, pending_session):
                session.forwarding = False
            tasks = (
                self._lifetime_task,
                self._reconnect_task,
                self._connect_task,
                self._cleanup_task,
            )
            self._lifetime_task = None
            self._reconnect_task = None
            self._connect_task = None
            self._cleanup_task = None

        await self._cancel_tasks(*tasks)
        close_error: BaseException | None = None
        for session in self._unique_sessions(active_session, pending_session):
            try:
                await self._close_session(session)
            except asyncio.CancelledError as error:
                if close_error is None:
                    close_error = error
            except Exception as error:  # noqa: BLE001 - collect every cleanup failure.
                if close_error is None:
                    close_error = error

        async with self._audio_lock:
            if close_error is None:
                self._session = None
                self._pending_session = None
                self._clear_credentials()
                self._state = _State.CLOSED
                self._closed.set()
            else:
                self._state = previous_state
            self._finish_event_stream()
        if close_error is not None:
            raise close_error

    def _install_session(self, session: _Session) -> None:
        session.iterator = session.client.events()
        self._session = session
        self._generation = session.generation
        self._state = _State.ACTIVE
        session.pump_task = asyncio.create_task(
            self._pump_events(session),
            name=f"voice-cua-asr-events-{session.generation}",
        )
        self._lifetime_task = asyncio.create_task(
            self._expire_session(session),
            name=f"voice-cua-asr-lifetime-{session.generation}",
        )
        self._put_event(VoiceLifecycleEvent(VoiceLifecycle.READY, session.generation))

    async def _expire_session(self, session: _Session) -> None:
        lifetime_task = asyncio.current_task()
        try:
            await asyncio.sleep(self._session_lifetime)
            async with self._audio_lock:
                if (
                    not self._terminal
                    and self._state is _State.ACTIVE
                    and self._session is session
                ):
                    self._begin_reconnect_locked(session, None)
        finally:
            if self._lifetime_task is lifetime_task:
                self._lifetime_task = None

    async def _pump_events(self, session: _Session) -> None:
        iterator = session.iterator
        assert iterator is not None
        failure_handled = False
        try:
            async for event in iterator:
                await self._forward_event(session, event)
                if not session.forwarding:
                    failure_handled = True
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - event iterators define failures.
            failure_handled = True
            await self._handle_active_failure(session, error)
        finally:
            session.stream_done.set()
            if (
                not failure_handled
                and not self._terminal
                and session.forwarding
                and self._session is session
            ):
                await self._handle_active_failure(
                    session,
                    ASREventStreamEndedError(
                        "The active ASR event stream ended unexpectedly."
                    ),
                )
            elif self._terminal and self._session is session:
                self._finish_event_stream()

    async def _forward_event(self, session: _Session, event: VoiceEvent) -> None:
        if not session.forwarding or self._session is not session:
            return
        if isinstance(event, VoiceWorkerFailure):
            await self._handle_active_failure(session, event.error)
            return
        if isinstance(event, SpeechStarted):
            async with self._audio_lock:
                if not self._is_active_session(session):
                    return
                session.latest_turn_id = event.turn_id
                self._put_event(event)
            return
        if isinstance(event, PartialTranscript):
            async with self._audio_lock:
                if not self._is_active_session(session):
                    return
                if event.turn_id != session.latest_turn_id:
                    return
                self._put_event(event)
            return
        if isinstance(event, FinalTranscript):
            async with self._audio_lock:
                if (
                    not session.forwarding
                    or self._session is not session
                    or self._state not in {_State.ACTIVE, _State.STOPPING}
                ):
                    return
                self._put_event(
                    SupervisedFinalTranscript(
                        generation=session.generation,
                        turn_id=event.turn_id,
                        transcript=event.transcript,
                        command_eligible=event.turn_id == session.latest_turn_id,
                    )
                )
            return
        self._put_event(event)

    async def _handle_active_failure(
        self, session: _Session, error: BaseException
    ) -> None:
        async with self._audio_lock:
            if not self._is_active_session(session):
                return
            if self._is_retryable(error):
                self._begin_reconnect_locked(session, error)
            else:
                self._fail_session_locked(session, error)

    def _begin_reconnect_locked(
        self,
        session: _Session,
        trigger_error: BaseException | None,
    ) -> None:
        if (
            self._terminal
            or self._session is not session
            or self._state is not _State.ACTIVE
        ):
            return
        session.forwarding = False
        self._state = _State.RECONNECTING
        lifetime_task = self._lifetime_task
        if lifetime_task is not None and lifetime_task is not asyncio.current_task():
            lifetime_task.cancel()
        self._lifetime_task = None
        next_generation = session.generation + 1
        if not self._put_event(
            VoiceLifecycleEvent(VoiceLifecycle.RECONNECTING, next_generation)
        ):
            return
        self._reconnect_task = asyncio.create_task(
            self._replace_session(session, trigger_error),
            name=f"voice-cua-asr-reconnect-{next_generation}",
        )

    async def _replace_session(
        self,
        old_session: _Session,
        trigger_error: BaseException | None,
    ) -> None:
        last_error = trigger_error
        try:
            try:
                await self._close_session(old_session)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - cleanup must fail closed.
                async with self._audio_lock:
                    if not self._terminal and self._session is old_session:
                        self._state = _State.FAILED
                        self._put_event(VoiceWorkerFailure(error))
                        self._finish_event_stream()
                return
            for attempt in range(self._max_reconnect_attempts):
                if self._terminal or self._session is not old_session:
                    return
                delay = self._reconnect_backoff[attempt]
                if delay:
                    await asyncio.sleep(delay)
                settings = self._settings
                meta_api_key = self._meta_api_key
                if settings is None or meta_api_key is None:
                    last_error = ASRSupervisorError(
                        "ASR reconnect credentials are unavailable."
                    )
                    break

                candidate: _Session | None = None
                try:
                    candidate = _Session(
                        old_session.generation + 1, self._client_factory()
                    )
                    self._pending_session = candidate
                    await asyncio.wait_for(
                        candidate.client.connect(
                            settings=settings, access_token=meta_api_key
                        ),
                        timeout=self._reconnect_timeout,
                    )
                except asyncio.CancelledError:
                    if candidate is not None:
                        with suppress(BaseException):
                            await self._close_session(candidate)
                    raise
                except Exception as error:  # noqa: BLE001 - retry policy classifies adapters.
                    last_error = error
                    cleanup_error: BaseException | None = None
                    if candidate is not None:
                        try:
                            await self._close_session(candidate)
                        except asyncio.CancelledError as cleanup_failure:
                            cleanup_error = cleanup_failure
                        except Exception as cleanup_failure:  # noqa: BLE001
                            cleanup_error = cleanup_failure
                    if cleanup_error is not None:
                        last_error = cleanup_error
                        break
                    if self._pending_session is candidate:
                        self._pending_session = None
                    if not self._is_retryable(error):
                        break
                    continue

                async with self._audio_lock:
                    if self._terminal or self._session is not old_session:
                        assert candidate is not None
                        await self._close_session(candidate)
                        return
                    self._pending_session = None
                    self._install_session(candidate)
                    return

            failure = last_error or ASRSupervisorError(
                "ASR reconnect attempts were exhausted."
            )
            async with self._audio_lock:
                if not self._terminal and self._session is old_session:
                    self._session = None
                    self._clear_credentials()
                    self._state = _State.FAILED
                    self._put_event(VoiceWorkerFailure(failure))
                    self._finish_event_stream()
                    if self._pending_session is None:
                        self._closed.set()
        finally:
            if self._reconnect_task is asyncio.current_task():
                self._reconnect_task = None

    def _fail_session_locked(self, session: _Session, error: BaseException) -> None:
        session.forwarding = False
        lifetime_task = self._lifetime_task
        if lifetime_task is not None and lifetime_task is not asyncio.current_task():
            lifetime_task.cancel()
        self._lifetime_task = None
        self._state = _State.FAILED
        self._put_event(VoiceWorkerFailure(error))
        self._finish_event_stream()
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self._cleanup_failed_session(session),
                name=f"voice-cua-asr-cleanup-{session.generation}",
            )

    async def _cleanup_failed_session(self, session: _Session) -> None:
        try:
            await self._close_session(session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - explicit disconnect can retry cleanup.
            return
        async with self._audio_lock:
            if self._session is session:
                self._session = None
                self._clear_credentials()
                self._closed.set()
            if self._cleanup_task is asyncio.current_task():
                self._cleanup_task = None

    def _is_active_session(self, session: _Session) -> bool:
        return (
            not self._terminal
            and self._state is _State.ACTIVE
            and session.forwarding
            and self._session is session
        )

    @staticmethod
    def _is_retryable(error: BaseException) -> bool:
        if isinstance(error, ASRConnectionClosedError):
            return error.classification.may_reconnect_without_configuration_change
        return isinstance(
            error,
            (
                ASRServerReportedError,
                ASRTransportError,
                ASREventStreamEndedError,
                OSError,
                TimeoutError,
            ),
        )

    async def _close_session(self, session: _Session) -> None:
        async with session.close_lock:
            if session.closed:
                return
            session.forwarding = False
            pump = session.pump_task
            if (
                pump is not None
                and pump is not asyncio.current_task()
                and not pump.done()
            ):
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
            iterator = session.iterator
            close_iterator = getattr(iterator, "aclose", None)
            iterator_error: BaseException | None = None
            if callable(close_iterator):
                try:
                    await cast(Callable[[], Awaitable[object]], close_iterator)()
                except asyncio.CancelledError as error:
                    iterator_error = error
                except Exception as error:  # noqa: BLE001 - transport cleanup continues.
                    iterator_error = error
            disconnect_error: BaseException | None = None
            try:
                await session.client.disconnect()
            except asyncio.CancelledError as error:
                disconnect_error = error
            except Exception as error:  # noqa: BLE001 - preserve cleanup state.
                disconnect_error = error
            if iterator_error is not None or disconnect_error is not None:
                session.cleanup_failed = True
                if disconnect_error is not None:
                    if iterator_error is not None:
                        raise disconnect_error from iterator_error
                    raise disconnect_error
                assert iterator_error is not None
                raise iterator_error
            session.cleanup_failed = False
            session.closed = True
            session.stream_done.set()

    async def _cancel_tasks(self, *tasks: asyncio.Task[None] | None) -> None:
        current_task = asyncio.current_task()
        active_tasks = tuple(
            task
            for task in tasks
            if task is not None and task is not current_task and not task.done()
        )
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

    @staticmethod
    def _unique_sessions(*sessions: _Session | None) -> tuple[_Session, ...]:
        unique: list[_Session] = []
        for session in sessions:
            if session is not None and all(session is not prior for prior in unique):
                unique.append(session)
        return tuple(unique)

    def _put_event(self, event: VoiceEvent) -> bool:
        if self._events_finished:
            return False
        items = self._take_buffered_events()
        if isinstance(event, (SpeechStarted, PartialTranscript)):
            items = [item for item in items if not isinstance(item, PartialTranscript)]
        elif isinstance(event, SupervisedFinalTranscript):
            items = [
                item
                for item in items
                if not isinstance(item, PartialTranscript)
                or item.turn_id != event.turn_id
            ]

        if (
            isinstance(event, PartialTranscript)
            and len(items) >= self._event_buffer_size
        ):
            self._restore_buffered_events(items)
            return True
        if len(items) >= self._event_buffer_size:
            partial_index = next(
                (
                    index
                    for index, item in enumerate(items)
                    if isinstance(item, PartialTranscript)
                ),
                None,
            )
            if partial_index is None:
                self._fail_event_buffer_overflow()
                return False
            items.pop(partial_index)
        items.append(event)
        self._restore_buffered_events(items)
        return True

    def _fail_event_buffer_overflow(self) -> None:
        while not self._events.empty():
            self._events.get_nowait()
        session = self._session
        if session is not None:
            session.forwarding = False
        lifetime_task = self._lifetime_task
        if lifetime_task is not None and lifetime_task is not asyncio.current_task():
            lifetime_task.cancel()
        self._lifetime_task = None
        self._state = _State.FAILED
        self._events_finished = True
        self._events.put_nowait(
            VoiceWorkerFailure(
                ASREventBufferOverflowError(
                    "The bounded ASR event buffer filled with authoritative events."
                )
            )
        )
        self._events.put_nowait(_EVENT_STREAM_END)
        if session is not None and (
            self._cleanup_task is None or self._cleanup_task.done()
        ):
            self._cleanup_task = asyncio.create_task(
                self._cleanup_failed_session(session),
                name=f"voice-cua-asr-overflow-cleanup-{session.generation}",
            )

    def _take_buffered_events(self) -> list[VoiceEvent]:
        items: list[VoiceEvent] = []
        while not self._events.empty():
            item = self._events.get_nowait()
            if item is not _EVENT_STREAM_END:
                items.append(cast(VoiceEvent, item))
        return items

    def _restore_buffered_events(self, items: list[VoiceEvent]) -> None:
        for item in items:
            self._events.put_nowait(item)

    def _reset_event_stream(self) -> None:
        self._events = asyncio.Queue(maxsize=self._event_buffer_size + 2)
        self._events_finished = False

    def _finish_event_stream(self) -> None:
        if self._events_finished:
            return
        self._events_finished = True
        self._events.put_nowait(_EVENT_STREAM_END)

    def _clear_credentials(self) -> None:
        self._settings = None
        self._meta_api_key = None


def _default_client_factory() -> ASRSession:
    return cast(ASRSession, VoiceASRClient())
