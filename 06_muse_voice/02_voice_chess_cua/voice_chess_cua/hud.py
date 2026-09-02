# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Immutable heads-up-display state, reduction, and presentation."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

MAX_TRANSCRIPT_LENGTH = 160
MAX_ERROR_LENGTH = 120
MAX_STATUS_VALUE_LENGTH = 80
MAX_WAVEFORM_SAMPLES = 32


class HUDPhase(StrEnum):
    STARTING = "Starting"
    LISTENING = "Listening"
    HEARING_SPEECH = "Hearing speech"
    FINALIZING = "Finalizing"
    RECONNECTING = "Reconnecting"
    PLANNING = "Planning"
    MOVING = "Moving"
    WAITING_FOR_CHESS = "Waiting for Chess"
    PAUSED = "Paused"
    ERROR = "Error"
    STOPPING = "Stopping"


@dataclass(frozen=True, slots=True)
class HUDState:
    phase: HUDPhase = HUDPhase.STARTING
    transcript: str = ""
    error_message: str = ""
    turn: str = "Unknown"
    last_move: str = "No move yet"
    board_available: bool = False
    revision: int = 0
    partial_transcript: str = ""
    waveform: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", HUDPhase(self.phase))
        object.__setattr__(
            self, "transcript", normalize_final_transcript(self.transcript)
        )
        object.__setattr__(
            self,
            "partial_transcript",
            normalize_final_transcript(self.partial_transcript),
        )
        object.__setattr__(self, "waveform", _normalize_waveform(self.waveform))
        object.__setattr__(
            self,
            "error_message",
            _normalize_display_text(
                self.error_message, maximum_length=MAX_ERROR_LENGTH
            ),
        )
        object.__setattr__(
            self,
            "turn",
            _normalize_display_text(self.turn, maximum_length=MAX_STATUS_VALUE_LENGTH)
            or "Unknown",
        )
        object.__setattr__(
            self,
            "last_move",
            _normalize_display_text(
                self.last_move, maximum_length=MAX_STATUS_VALUE_LENGTH
            )
            or "Unavailable",
        )
        if self.phase is not HUDPhase.ERROR and self.error_message:
            raise ValueError("error_message is only valid during the Error phase")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("revision must be a non-negative integer")

    @property
    def final_transcript(self) -> str:
        return self.transcript


@dataclass(frozen=True, slots=True)
class HUDUpdate:
    """One typed update; omitted fields retain their previous value."""

    phase: HUDPhase | None = None
    final_transcript: str | None = None
    error_message: str | None = None
    turn: str | None = None
    last_move: str | None = None
    board_available: bool | None = None
    clear_transcript: bool = False
    partial_transcript: str | None = None
    waveform_sample: float | None = None
    clear_partial_transcript: bool = False
    clear_waveform: bool = False

    def __post_init__(self) -> None:
        if self.phase is not None:
            object.__setattr__(self, "phase", HUDPhase(self.phase))
        if self.clear_transcript and self.final_transcript is not None:
            raise ValueError("an update cannot clear and replace the transcript")
        if self.clear_partial_transcript and self.partial_transcript is not None:
            raise ValueError(
                "an update cannot clear and replace the partial transcript"
            )
        if self.clear_waveform and self.waveform_sample is not None:
            raise ValueError("an update cannot clear and append to the waveform")
        if self.waveform_sample is not None:
            object.__setattr__(
                self,
                "waveform_sample",
                _normalize_waveform_sample(self.waveform_sample),
            )

    @classmethod
    def starting(cls) -> HUDUpdate:
        return cls(
            phase=HUDPhase.STARTING,
            turn="Unknown",
            last_move="No move yet",
            board_available=False,
            clear_transcript=True,
            clear_partial_transcript=True,
            clear_waveform=True,
        )

    @classmethod
    def listening(cls) -> HUDUpdate:
        return cls(phase=HUDPhase.LISTENING)

    @classmethod
    def hearing(cls) -> HUDUpdate:
        return cls(
            phase=HUDPhase.HEARING_SPEECH,
            clear_partial_transcript=True,
        )

    @classmethod
    def partial(cls, transcript: str) -> HUDUpdate:
        return cls(partial_transcript=normalize_final_transcript(transcript))

    @classmethod
    def waveform(cls, sample: float) -> HUDUpdate:
        return cls(waveform_sample=_normalize_waveform_sample(sample))

    @classmethod
    def append_waveform(cls, sample: float) -> HUDUpdate:
        return cls.waveform(sample)

    @classmethod
    def clear_waveform_samples(cls) -> HUDUpdate:
        return cls(clear_waveform=True)

    @classmethod
    def finalizing(cls) -> HUDUpdate:
        return cls(phase=HUDPhase.FINALIZING)

    @classmethod
    def reconnecting(cls) -> HUDUpdate:
        return cls(phase=HUDPhase.RECONNECTING)

    @classmethod
    def fresh_voice_session(cls) -> HUDUpdate:
        return cls(clear_transcript=True, clear_partial_transcript=True)

    @classmethod
    def heard(cls, transcript: str) -> HUDUpdate:
        return cls(final_transcript=transcript, clear_partial_transcript=True)

    @classmethod
    def failed(cls, message: str) -> HUDUpdate:
        return cls(phase=HUDPhase.ERROR, error_message=message)


@dataclass(frozen=True, slots=True)
class HUDPresentation:
    revision: int
    voice: str
    turn: str
    last_move: str
    heard: str
    detail: str | None
    board_available: bool
    is_busy: bool
    is_error: bool
    waveform: tuple[float, ...] = ()

    @property
    def status(self) -> str:
        return self.voice

    @property
    def transcript(self) -> str | None:
        return None if self.heard == "-" else self.heard


_BUSY_PHASES = frozenset(
    {
        HUDPhase.STARTING,
        HUDPhase.FINALIZING,
        HUDPhase.RECONNECTING,
        HUDPhase.PLANNING,
        HUDPhase.MOVING,
        HUDPhase.WAITING_FOR_CHESS,
        HUDPhase.STOPPING,
    }
)


def reduce_hud(state: HUDState, update: HUDUpdate) -> HUDState:
    """Return a newer immutable HUD snapshot."""

    phase = state.phase if update.phase is None else update.phase
    transcript = state.transcript
    if update.clear_transcript:
        transcript = ""
    elif update.final_transcript is not None:
        transcript = normalize_final_transcript(update.final_transcript)

    partial_transcript = state.partial_transcript
    if update.clear_partial_transcript:
        partial_transcript = ""
    elif update.partial_transcript is not None:
        partial_transcript = normalize_final_transcript(update.partial_transcript)

    waveform = state.waveform
    if update.clear_waveform:
        waveform = ()
    elif update.waveform_sample is not None:
        waveform = (*waveform, update.waveform_sample)[-MAX_WAVEFORM_SAMPLES:]

    if phase is HUDPhase.ERROR:
        error_message = (
            state.error_message
            if update.error_message is None
            else _normalize_display_text(
                update.error_message, maximum_length=MAX_ERROR_LENGTH
            )
        )
    else:
        error_message = ""

    return HUDState(
        phase=phase,
        transcript=transcript,
        error_message=error_message,
        turn=state.turn if update.turn is None else update.turn,
        last_move=state.last_move if update.last_move is None else update.last_move,
        board_available=(
            state.board_available
            if update.board_available is None
            else update.board_available
        ),
        revision=state.revision + 1,
        partial_transcript=partial_transcript,
        waveform=waveform,
    )


def present_hud(state: HUDState) -> HUDPresentation:
    """Build the presentation for the AppKit overlay's three visible rows."""

    voice = state.phase.value
    if not state.board_available and state.phase is HUDPhase.LISTENING:
        voice = "Board unavailable"
    return HUDPresentation(
        revision=state.revision,
        voice=voice,
        turn=state.turn,
        last_move=state.last_move,
        heard=state.partial_transcript or state.transcript or "-",
        detail=state.error_message or None,
        board_available=state.board_available,
        is_busy=state.phase in _BUSY_PHASES,
        is_error=state.phase is HUDPhase.ERROR,
        waveform=state.waveform,
    )


def normalize_final_transcript(
    transcript: str,
    *,
    maximum_length: int = MAX_TRANSCRIPT_LENGTH,
) -> str:
    """Normalize an authoritative final to a bounded in-memory display value."""

    if not isinstance(transcript, str):
        raise TypeError("transcript must be a string")
    if isinstance(maximum_length, bool) or not isinstance(maximum_length, int):
        raise TypeError("maximum_length must be an integer")
    if maximum_length < 1:
        raise ValueError("maximum_length must be positive")
    return _normalize_display_text(transcript, maximum_length=maximum_length)


def _normalize_waveform(waveform: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(waveform, tuple):
        raise TypeError("waveform must be a tuple")
    return tuple(_normalize_waveform_sample(sample) for sample in waveform)[
        -MAX_WAVEFORM_SAMPLES:
    ]


def _normalize_waveform_sample(sample: float) -> float:
    if isinstance(sample, bool) or not isinstance(sample, (int, float)):
        raise TypeError("waveform sample must be a number")
    value = float(sample)
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("waveform sample must be finite and between 0 and 1")
    return value


def _normalize_display_text(value: str, *, maximum_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    without_controls = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in normalized
    )
    single_line = " ".join(without_controls.split())
    if len(single_line) <= maximum_length:
        return single_line
    marker = "." * min(3, maximum_length)
    return f"{single_line[: maximum_length - len(marker)].rstrip()}{marker}"
