# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Async public realtime ASR transport."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from websockets.exceptions import ConnectionClosed

from voice_chess_cua.runtime.ports import (
    FinalTranscript,
    PartialTranscript,
    SpeechEnded,
    SpeechStarted,
    VoiceEvent,
    VoiceWorkerFailure,
)

from .asr_diagnostics import ASRClientError, ASRTransportError, ASRTransportPhase
from .asr_protocol import (
    END_STREAM_DATA,
    ASRProtocolError,
    HandshakeRequest,
    HandshakeResponse,
    Mode,
    ServerError,
    SpeechComplete,
    SpeechEnd,
    SpeechStart,
    Transcript,
    decode_server_message,
    snapshot_keywords,
)
from .chess_vocabulary import CHESS_ASR_KEYWORDS


class WebSocketConnection(Protocol):
    close_code: int | None
    close_reason: str | None

    async def send(self, message: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


WebSocketConnector = Callable[[str], Awaitable[WebSocketConnection]]
SessionIDFactory = Callable[[], str]
type ASRClientEvent = VoiceEvent


class AlreadyConnectedError(ASRClientError):
    pass


class InvalidEndpointError(ASRClientError):
    pass


class MissingAccessTokenError(ASRClientError):
    pass


class MissingModelError(ASRClientError):
    pass


class InvalidASRConfigurationError(ASRClientError):
    pass


class InvalidHandshakeResponseError(ASRClientError):
    pass


class HandshakeRejectedError(ASRClientError):
    def __init__(self, message: str) -> None:
        super().__init__(f"ASR rejected the handshake: {message}")
        self.server_message = message


class ASREventBufferOverflowError(ASRClientError):
    pass


class _StopReceiveLoop(Exception):
    pass


class HandshakeIncompleteError(ASRClientError):
    pass


class AudioAlreadyEndedError(ASRClientError):
    pass


class ASRServerReportedError(ASRClientError):
    def __init__(self, message: str, session_id: str | None = None) -> None:
        super().__init__(message)
        self.server_message = message
        self.session_id = session_id


class CloseCategory(StrEnum):
    NORMAL_COMPLETION = "normal_completion"
    INVALID_REQUEST = "invalid_request"
    RETRYABLE_SERVER_FAILURE = "retryable_server_failure"
    RATE_LIMITED = "rate_limited"
    ABNORMAL = "abnormal"


@dataclass(frozen=True, slots=True)
class CloseClassification:
    category: CloseCategory
    code: int

    @classmethod
    def from_code(cls, code: int) -> CloseClassification:
        category = {
            1000: CloseCategory.NORMAL_COMPLETION,
            1008: CloseCategory.INVALID_REQUEST,
            1011: CloseCategory.RETRYABLE_SERVER_FAILURE,
            1013: CloseCategory.RATE_LIMITED,
        }.get(code, CloseCategory.ABNORMAL)
        return cls(category=category, code=code)

    @property
    def may_reconnect_without_configuration_change(self) -> bool:
        return self.category not in {
            CloseCategory.NORMAL_COMPLETION,
            CloseCategory.INVALID_REQUEST,
        }


class ASRConnectionClosedError(ASRClientError):
    def __init__(
        self,
        classification: CloseClassification,
        reason: str | None = None,
    ) -> None:
        detail = f"ASR WebSocket closed with code {classification.code}"
        if reason:
            detail = f"{detail}: {reason}"
        super().__init__(detail)
        self.classification = classification
        self.reason = reason


_EVENT_STREAM_END = object()
_DEFAULT_EVENT_BUFFER_SIZE = 256
_DEFAULT_DISCONNECT_TIMEOUT = 1.0
_PROTOCOL_ERROR_CLOSE_CODE = 1002
_GOING_AWAY_CLOSE_CODE = 1001
_ABNORMAL_CLOSE_CODE = 1006


async def _default_connector(url: str) -> WebSocketConnection:
    # Keep the optional network dependency out of import-time code and unit tests.
    from websockets.asyncio.client import connect

    return cast(WebSocketConnection, await connect(url))


def _default_session_id() -> str:
    return f"voice-chess-{str(uuid4()).lower()}"


def connection_url(endpoint: str, session_id: str | None = None) -> str:
    """Validate an endpoint and add or replace its ``sessionId`` query item."""

    try:
        components = urlsplit(endpoint)
        port = components.port
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidEndpointError(
            "The ASR endpoint is not a valid secure WebSocket URL."
        ) from error
    if components.scheme.lower() != "wss" or not components.hostname:
        raise InvalidEndpointError(
            "The ASR endpoint is not a valid secure WebSocket URL."
        )
    del port

    if not session_id:
        return endpoint
    query_items = [
        (name, value)
        for name, value in parse_qsl(components.query, keep_blank_values=True)
        if name != "sessionId"
    ]
    query_items.append(("sessionId", session_id))
    return urlunsplit(components._replace(query=urlencode(query_items, doseq=True)))


class VoiceASRClient:
    """One-session ASR client implementing the runtime's asynchronous ASR port."""

    def __init__(
        self,
        *,
        connector: WebSocketConnector | None = None,
        session_id_factory: SessionIDFactory = _default_session_id,
        event_buffer_size: int = _DEFAULT_EVENT_BUFFER_SIZE,
        disconnect_timeout: float = _DEFAULT_DISCONNECT_TIMEOUT,
        mode: Mode = Mode.ENDPOINTING,
        keywords: Iterable[str] | None = None,
    ) -> None:
        if event_buffer_size <= 0:
            raise ValueError("event_buffer_size must be positive")
        if disconnect_timeout < 0:
            raise ValueError("disconnect_timeout must not be negative")
        if mode is not Mode.ENDPOINTING:
            raise InvalidASRConfigurationError(
                "The public ASR client requires ENDPOINTING mode."
            )
        requested_keywords = (
            CHESS_ASR_KEYWORDS if keywords is None else snapshot_keywords(keywords)
        )
        if requested_keywords != CHESS_ASR_KEYWORDS:
            raise InvalidASRConfigurationError(
                "The public ASR client requires the fixed chess keyword vocabulary."
            )
        self._connector = connector or _default_connector
        self._session_id_factory = session_id_factory
        self._event_buffer_size = event_buffer_size
        self._disconnect_timeout = disconnect_timeout
        self._mode = Mode.ENDPOINTING
        self._keywords = CHESS_ASR_KEYWORDS
        self._socket: WebSocketConnection | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[ASRClientEvent | object] = asyncio.Queue(
            maxsize=event_buffer_size + 2
        )
        self._events_finished = True
        self._closed = asyncio.Event()
        self._closed.set()
        self._disconnect_lock = asyncio.Lock()
        self._connecting = False
        self._handshake_complete = False
        self._end_stream_sent = False
        self._active_turn_id: int | None = None
        self._completed_turn_ids: set[int] = set()
        self._connection_url: str | None = None
        self._requested_session_id: str | None = None
        self._server_session_id: str | None = None

    @property
    def connection_url(self) -> str | None:
        return self._connection_url

    @property
    def requested_session_id(self) -> str | None:
        return self._requested_session_id

    @property
    def session_id(self) -> str | None:
        return self._server_session_id

    async def connect(
        self,
        *,
        settings: object,
        access_token: str,
    ) -> None:
        if self._socket is not None or self._connecting:
            raise AlreadyConnectedError("An ASR connection is already active.")
        if not isinstance(access_token, str) or not access_token:
            raise MissingAccessTokenError("The Meta Model API key is missing.")

        endpoint = getattr(settings, "endpoint", None)
        model = getattr(settings, "model", None)
        if not isinstance(model, str) or not model.strip():
            raise MissingModelError("The ASR model is missing.")
        if not isinstance(endpoint, str):
            raise InvalidEndpointError(
                "The ASR endpoint is not a valid secure WebSocket URL."
            )

        requested_session_id = self._session_id_factory()
        if not isinstance(requested_session_id, str) or not requested_session_id:
            raise ValueError("session_id_factory must return a non-empty string")
        url = connection_url(endpoint, requested_session_id)

        self._connecting = True
        self._reset_event_stream()
        self._closed = asyncio.Event()
        self._requested_session_id = requested_session_id
        self._connection_url = url
        self._server_session_id = None
        socket: WebSocketConnection | None = None
        try:
            try:
                socket = await self._connector(url)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise ASRTransportError(ASRTransportPhase.WEBSOCKET_CONNECT) from error

            self._socket = socket
            try:
                await socket.send(
                    HandshakeRequest(
                        access_token=access_token,
                        model=model,
                        mode=self._mode,
                        keywords=self._keywords,
                    ).to_json()
                )
                first_message = await socket.recv()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise ASRTransportError(ASRTransportPhase.HANDSHAKE_EXCHANGE) from error

            if not isinstance(first_message, str):
                raise InvalidHandshakeResponseError(
                    "The ASR server returned an unexpected handshake response."
                )
            try:
                server_message = decode_server_message(first_message)
            except ASRProtocolError:
                server_message = None
            if isinstance(server_message, ServerError):
                raise HandshakeRejectedError(server_message.message)
            try:
                response = HandshakeResponse.from_json(first_message)
            except ASRProtocolError as error:
                raise InvalidHandshakeResponseError(
                    "The ASR server returned an unexpected handshake response."
                ) from error

            self._server_session_id = response.session_id
            self._handshake_complete = True
            self._receive_task = asyncio.create_task(
                self._run_receive_loop(socket),
                name="voice-cua-asr-receive",
            )
            return
        except BaseException:
            if socket is not None:
                await self._close_socket_bounded(socket, _PROTOCOL_ERROR_CLOSE_CODE)
            self._clear_connection(socket)
            self._finish_event_stream()
            raise
        finally:
            self._connecting = False

    def events(self) -> AsyncIterator[ASRClientEvent]:
        queue = self._events

        async def iterate() -> AsyncIterator[ASRClientEvent]:
            while True:
                item = await queue.get()
                if item is _EVENT_STREAM_END:
                    return
                yield cast(ASRClientEvent, item)

        return iterate()

    async def send_audio(self, frame: bytes) -> None:
        socket = self._ready_socket()
        if self._end_stream_sent:
            raise AudioAlreadyEndedError(
                "Audio has already ended for this ASR session."
            )
        if not isinstance(frame, bytes):
            raise TypeError("ASR audio frames must be bytes")
        if not frame:
            return
        await socket.send(frame)

    async def end_stream(self) -> None:
        socket = self._ready_socket()
        if self._end_stream_sent:
            return
        self._end_stream_sent = True
        await socket.send(END_STREAM_DATA.decode("utf-8"))

    async def wait_closed(self, timeout: float) -> bool:
        if self._socket is None or self._closed.is_set():
            return True
        if timeout <= 0:
            return False
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def disconnect(self) -> None:
        async with self._disconnect_lock:
            socket = self._socket
            receive_task = self._receive_task
            self._socket = None
            self._receive_task = None
            self._handshake_complete = False
            self._end_stream_sent = False
            self._active_turn_id = None

            if receive_task is not None and receive_task is not asyncio.current_task():
                receive_task.cancel()
                with suppress(asyncio.CancelledError):
                    await receive_task
            if socket is not None:
                await self._close_socket_bounded(socket, _GOING_AWAY_CLOSE_CODE)
            self._closed.set()
            self._finish_event_stream()

    async def _run_receive_loop(self, socket: WebSocketConnection) -> None:
        try:
            while True:
                try:
                    message = await socket.recv()
                except asyncio.CancelledError:
                    raise
                except (ConnectionClosed, OSError) as error:
                    closed_error = self._closed_error(error, socket)
                    if not (
                        self._end_stream_sent
                        and closed_error.classification.category
                        is CloseCategory.NORMAL_COMPLETION
                    ):
                        self._put_event(VoiceWorkerFailure(closed_error))
                    self._mark_remote_closed(socket)
                    return

                if not isinstance(message, str):
                    continue
                try:
                    server_message = decode_server_message(message)
                except ASRProtocolError as error:
                    self._put_event(VoiceWorkerFailure(error))
                    return

                if isinstance(server_message, SpeechStart):
                    self._active_turn_id = server_message.turn_id
                    self._put_event(SpeechStarted(str(server_message.turn_id)))
                elif isinstance(server_message, SpeechEnd):
                    self._put_event(SpeechEnded(str(server_message.turn_id)))
                    if self._active_turn_id == server_message.turn_id:
                        self._active_turn_id = None
                elif isinstance(server_message, Transcript):
                    if self._active_turn_id is not None:
                        self._put_event(
                            PartialTranscript(
                                str(self._active_turn_id),
                                server_message.transcript,
                            )
                        )
                elif isinstance(server_message, SpeechComplete):
                    if (
                        self._mode is Mode.ENDPOINTING
                        and server_message.turn_id not in self._completed_turn_ids
                    ):
                        self._completed_turn_ids.add(server_message.turn_id)
                        self._put_event(
                            FinalTranscript(
                                str(server_message.turn_id), server_message.transcript
                            )
                        )
                    if self._active_turn_id == server_message.turn_id:
                        self._active_turn_id = None
                elif isinstance(server_message, ServerError):
                    self._put_event(
                        VoiceWorkerFailure(
                            ASRServerReportedError(
                                server_message.message,
                                server_message.session_id,
                            )
                        )
                    )
                    return
        except _StopReceiveLoop:
            return
        finally:
            if self._receive_task is asyncio.current_task():
                self._receive_task = None
            self._finish_event_stream()

    def _ready_socket(self) -> WebSocketConnection:
        if self._socket is None or not self._handshake_complete:
            raise HandshakeIncompleteError("The ASR handshake is not complete.")
        return self._socket

    def _reset_event_stream(self) -> None:
        # Reserved failure and terminator slots make overflow explicit without evicting events.
        self._events = asyncio.Queue(maxsize=self._event_buffer_size + 2)
        self._events_finished = False
        self._completed_turn_ids.clear()

    def _put_event(self, event: ASRClientEvent) -> None:
        if self._events_finished:
            return
        items = self._take_buffered_events()
        if isinstance(event, (SpeechStarted, PartialTranscript)):
            items = [item for item in items if not isinstance(item, PartialTranscript)]
        elif isinstance(event, FinalTranscript):
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
            return
        if len(items) >= self._event_buffer_size:
            self._events_finished = True
            self._restore_buffered_events(items)
            self._events.put_nowait(
                VoiceWorkerFailure(
                    ASREventBufferOverflowError(
                        "ASR event buffer filled before the runtime consumed it."
                    )
                )
            )
            self._events.put_nowait(_EVENT_STREAM_END)
            raise _StopReceiveLoop
        items.append(event)
        self._restore_buffered_events(items)

    def _take_buffered_events(self) -> list[ASRClientEvent]:
        items: list[ASRClientEvent] = []
        while not self._events.empty():
            item = self._events.get_nowait()
            if item is not _EVENT_STREAM_END:
                items.append(cast(ASRClientEvent, item))
        return items

    def _restore_buffered_events(self, items: list[ASRClientEvent]) -> None:
        for item in items:
            self._events.put_nowait(item)

    def _finish_event_stream(self) -> None:
        if self._events_finished:
            return
        self._events_finished = True
        self._events.put_nowait(_EVENT_STREAM_END)

    def _mark_remote_closed(self, socket: WebSocketConnection) -> None:
        if self._socket is socket:
            self._clear_connection(socket, preserve_end_stream=True)

    def _clear_connection(
        self,
        socket: WebSocketConnection | None,
        *,
        preserve_end_stream: bool = False,
    ) -> None:
        if socket is not None and self._socket is not socket:
            return
        self._socket = None
        self._handshake_complete = False
        if not preserve_end_stream:
            self._end_stream_sent = False
        self._active_turn_id = None
        self._closed.set()

    async def _close_socket_bounded(
        self,
        socket: WebSocketConnection,
        code: int,
    ) -> None:
        close_task = asyncio.create_task(socket.close(code=code))
        try:
            await asyncio.wait_for(
                asyncio.shield(close_task),
                timeout=self._disconnect_timeout,
            )
        except TimeoutError:
            close_task.cancel()
            close_task.add_done_callback(self._consume_task_result)
        except asyncio.CancelledError:
            close_task.cancel()
            close_task.add_done_callback(self._consume_task_result)
            raise
        except (ConnectionClosed, OSError):
            # The connection is already unusable; local state cleanup still completes.
            return

    @staticmethod
    def _consume_task_result(task: asyncio.Task[None]) -> None:
        with suppress(BaseException):
            task.result()

    @staticmethod
    def _closed_error(
        error: BaseException,
        socket: WebSocketConnection,
    ) -> ASRConnectionClosedError:
        code = getattr(error, "code", None)
        reason = getattr(error, "reason", None)
        received = getattr(error, "rcvd", None)
        if not isinstance(code, int) or isinstance(code, bool):
            code = getattr(received, "code", None)
        if not isinstance(reason, str):
            reason = getattr(received, "reason", None)
        if not isinstance(code, int) or isinstance(code, bool):
            code = socket.close_code
        if not isinstance(reason, str):
            reason = socket.close_reason
        if not isinstance(code, int) or isinstance(code, bool):
            code = _ABNORMAL_CLOSE_CODE
        if not isinstance(reason, str) or not reason:
            reason = None
        return ASRConnectionClosedError(
            CloseClassification.from_code(code),
            reason,
        )
