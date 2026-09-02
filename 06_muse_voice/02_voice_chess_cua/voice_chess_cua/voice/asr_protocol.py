# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""JSON envelopes for the public realtime ASR protocol."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar


class ASRProtocolError(ValueError):
    pass


class Mode(StrEnum):
    DEFAULT = "DEFAULT"
    ENDPOINTING = "ENDPOINTING"


class AudioEncoding(StrEnum):
    PCM_24KHZ = "PCM_24KHZ"


class PartialMode(StrEnum):
    CUMULATIVE = "CUMULATIVE"


MAX_KEYWORD_COUNT = 50


def snapshot_keywords(keywords: Iterable[str] | None) -> tuple[str, ...]:
    if keywords is None:
        return ()
    if isinstance(keywords, str):
        raise TypeError("ASR keywords must be an iterable of strings, not a string")
    snapshot = tuple(keywords)
    if len(snapshot) > MAX_KEYWORD_COUNT:
        raise ValueError(
            f"ASR keywords must contain at most {MAX_KEYWORD_COUNT} entries"
        )
    for keyword in snapshot:
        if not isinstance(keyword, str):
            raise TypeError("every ASR keyword must be a string")
        if not keyword.strip():
            raise ValueError("ASR keywords must not be empty or whitespace-only")
    return snapshot


@dataclass(frozen=True, slots=True)
class Authorization:
    access_token: str

    def to_dict(self) -> dict[str, str]:
        return {"accessToken": self.access_token}


@dataclass(frozen=True, slots=True, init=False)
class HandshakeRequest:
    authorization: Authorization
    model: str
    mode: Mode
    audio_encoding: AudioEncoding
    partial_mode: PartialMode
    emit_audio_progress: bool
    keywords: tuple[str, ...]

    def __init__(
        self,
        access_token: str,
        model: str,
        mode: Mode = Mode.ENDPOINTING,
        keywords: Iterable[str] | None = None,
    ) -> None:
        object.__setattr__(self, "authorization", Authorization(access_token))
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "audio_encoding", AudioEncoding.PCM_24KHZ)
        object.__setattr__(self, "partial_mode", PartialMode.CUMULATIVE)
        object.__setattr__(self, "emit_audio_progress", False)
        object.__setattr__(self, "keywords", snapshot_keywords(keywords))

    @classmethod
    def create(
        cls,
        access_token: str,
        model: str,
        mode: Mode = Mode.ENDPOINTING,
        keywords: Iterable[str] | None = None,
    ) -> HandshakeRequest:
        return cls(access_token, model, mode, keywords)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "mode": self.mode.value,
            "authorization": self.authorization.to_dict(),
            "audioEncoding": self.audio_encoding.value,
            "model": self.model,
            "partialMode": self.partial_mode.value,
            "emitAudioProgress": self.emit_audio_progress,
        }
        if self.keywords:
            value["keywords"] = list(self.keywords)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class HandshakeResponse:
    session_id: str

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> HandshakeResponse:
        value = _json_object(data)
        return cls(_required_str(value, "sessionId"))


@dataclass(frozen=True, slots=True)
class Transcript:
    transcript: str
    final: bool
    audio_processed_ms: int
    type: ClassVar[str] = "transcript"


@dataclass(frozen=True, slots=True)
class SpeechStart:
    audio_processed_ms: int
    turn_id: int
    type: ClassVar[str] = "speechStart"


@dataclass(frozen=True, slots=True)
class SpeechEnd:
    audio_processed_ms: int
    turn_id: int
    type: ClassVar[str] = "speechEnd"


@dataclass(frozen=True, slots=True)
class SpeechComplete:
    audio_processed_ms: int
    turn_id: int
    transcript: str
    type: ClassVar[str] = "speechComplete"


@dataclass(frozen=True, slots=True)
class AudioProgress:
    audio_processed_ms: int
    type: ClassVar[str] = "audioProgress"


@dataclass(frozen=True, slots=True)
class ServerError:
    message: str
    session_id: str | None = None
    type: ClassVar[str] = "error"


@dataclass(frozen=True, slots=True)
class UnknownMessage:
    type: str


type ServerMessage = (
    Transcript
    | SpeechStart
    | SpeechEnd
    | SpeechComplete
    | AudioProgress
    | ServerError
    | UnknownMessage
)


def decode_server_message(
    data: str | bytes | bytearray | Mapping[str, Any],
) -> ServerMessage:
    value = dict(data) if isinstance(data, Mapping) else _json_object(data)
    message_type = _required_str(value, "type")
    if message_type == Transcript.type:
        final = value.get("final")
        if not isinstance(final, bool):
            raise ASRProtocolError("final must be a boolean")
        return Transcript(
            transcript=_required_str(value, "transcript"),
            final=final,
            audio_processed_ms=_required_int(value, "audioProcessedMs"),
        )
    if message_type == SpeechStart.type:
        return SpeechStart(
            audio_processed_ms=_required_int(value, "audioProcessedMs"),
            turn_id=_required_int(value, "turnId"),
        )
    if message_type == SpeechEnd.type:
        return SpeechEnd(
            audio_processed_ms=_required_int(value, "audioProcessedMs"),
            turn_id=_required_int(value, "turnId"),
        )
    if message_type == SpeechComplete.type:
        return SpeechComplete(
            audio_processed_ms=_required_int(value, "audioProcessedMs"),
            turn_id=_required_int(value, "turnId"),
            transcript=_required_str(value, "transcript"),
        )
    if message_type == AudioProgress.type:
        return AudioProgress(
            audio_processed_ms=_required_int(value, "audioProcessedMs")
        )
    if message_type == ServerError.type:
        session_id = value.get("sessionId")
        if session_id is not None and not isinstance(session_id, str):
            raise ASRProtocolError("sessionId must be a string or null")
        return ServerError(
            message=_required_str(value, "message"), session_id=session_id
        )
    return UnknownMessage(message_type)


def _json_object(data: str | bytes | bytearray) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
        raise ASRProtocolError("invalid ASR JSON") from error
    if not isinstance(value, dict):
        raise ASRProtocolError("ASR message must be a JSON object")
    return value


def _required_str(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ASRProtocolError(f"{key} must be a string")
    return result


def _required_int(value: Mapping[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ASRProtocolError(f"{key} must be an integer")
    if not -(2**63) <= result < 2**63:
        raise ASRProtocolError(f"{key} is outside Int64 range")
    return result


END_STREAM_DATA = b'{"type":"endStream"}'
