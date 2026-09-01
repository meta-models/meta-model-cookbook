# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from voice_chess_cua.domain.chess import ChessMove, ChessSquare

if TYPE_CHECKING:
    from voice_chess_cua.automation.move_executor import PreparedMove


@dataclass(frozen=True, slots=True)
class RuntimeCredentials:
    """Secrets loaded for one runtime session.

    Secret values must not be included in logs, exceptions, or runtime notices.
    """

    model_api_key: str


class TrackingFailureReason(StrEnum):
    SCREEN_CAPTURE_PERMISSION = "screen_capture_permission"
    WINDOW_DISCOVERY_TIMEOUT = "window_discovery_timeout"
    CAPTURE_TIMEOUT = "capture_timeout"
    WINDOW_UNAVAILABLE = "window_unavailable"
    WINDOW_AMBIGUOUS = "window_ambiguous"
    UNSUPPORTED_ASPECT = "unsupported_aspect"
    UNSUPPORTED_ORIENTATION = "unsupported_orientation"
    LAYOUT_MISMATCH = "layout_mismatch"
    DETECTION_FAILED = "detection_failed"


class TrackingStatus(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    ACQUIRING = "acquiring"
    STABLE = "stable"
    STALE = "stale"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class TrackingUpdate:
    status: TrackingStatus
    generation: int
    detection: object | None = None
    failure_reason: TrackingFailureReason | None = None


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    turn_id: str


@dataclass(frozen=True, slots=True)
class SpeechEnded:
    turn_id: str


@dataclass(frozen=True, slots=True)
class PartialTranscript:
    turn_id: str
    transcript: str


@dataclass(frozen=True, slots=True)
class FinalTranscript:
    turn_id: str
    transcript: str


@dataclass(frozen=True, slots=True)
class SupervisedFinalTranscript:
    generation: int
    turn_id: str
    transcript: str
    command_eligible: bool = True


@dataclass(frozen=True, slots=True)
class VoiceWorkerFailure:
    error: BaseException


class VoiceLifecycle(StrEnum):
    RECONNECTING = "reconnecting"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class VoiceLifecycleEvent:
    status: VoiceLifecycle
    generation: int


VoiceEvent = (
    SpeechStarted
    | SpeechEnded
    | PartialTranscript
    | FinalTranscript
    | SupervisedFinalTranscript
    | VoiceWorkerFailure
    | VoiceLifecycleEvent
)


@runtime_checkable
class SettingsPort(Protocol):
    async def load_validated(self) -> object:
        """Load and validate the fixed runtime settings."""


@runtime_checkable
class CredentialPort(Protocol):
    async def load_runtime_credentials(self) -> RuntimeCredentials:
        """Load the shared Meta Model API key without exposing its value."""


@runtime_checkable
class PermissionPort(Protocol):
    async def verify_required(self) -> None:
        """Raise if any required permission is unavailable; never prompt."""


@runtime_checkable
class ChessApplicationPort(Protocol):
    async def activate(self) -> object:
        """Activate the exact Apple Chess application or raise."""


@runtime_checkable
class GameStateObserverPort(Protocol):
    def observations(self, process_identifier: int) -> AsyncIterator[object]: ...

    def confirm_local_move(self, move: ChessMove) -> None: ...

    def reset(self) -> None: ...


@runtime_checkable
class TrackingPort(Protocol):
    async def start(self, *, generation: int) -> None: ...

    def updates(self) -> AsyncIterator[TrackingUpdate]: ...

    async def stop(self) -> None: ...


@runtime_checkable
class OverlayPort(Protocol):
    async def show_stable(
        self,
        detection: object,
        source: ChessSquare | None = None,
        destination: ChessSquare | None = None,
    ) -> bool:
        """Show the stable board geometry in the passive overlay."""

    async def update_hud(self, state: object) -> None:
        """Render a newer immutable HUD presentation when a panel is available."""

    async def clear_board(self) -> None:
        """Clear board graphics while preserving the passive HUD panel."""

    async def hide(self) -> None:
        """Marshal hiding the overlay to the AppKit main thread."""

    async def destroy(self) -> None:
        """Destroy overlay resources on the AppKit main thread."""


@runtime_checkable
class ASRPort(Protocol):
    @property
    def generation(self) -> int: ...

    async def connect(self, *, settings: object, access_token: str) -> None: ...

    def events(self) -> AsyncIterator[VoiceEvent]: ...

    async def send_audio(self, frame: bytes) -> None: ...

    async def end_stream(self) -> None: ...

    async def wait_closed(self, timeout: float) -> bool: ...

    async def disconnect(self) -> None: ...


@runtime_checkable
class AudioPort(Protocol):
    def set_transaction_busy(self, busy: bool) -> None: ...

    async def start(self) -> None: ...

    def frames(self) -> AsyncIterator[bytes]: ...

    async def stop(self) -> None: ...

    async def drain(self) -> None: ...


@runtime_checkable
class SnapshotProbePort(Protocol):
    async def game_snapshot(
        self,
        process_identifier: int,
    ) -> tuple[str, Mapping[str, str]]: ...


@runtime_checkable
class PreparedMoveExecutorPort(Protocol):
    async def prepare(
        self,
        move: ChessMove,
        *,
        expires_at: float | None = None,
    ) -> PreparedMove: ...

    async def execute_prepared(self, prepared: PreparedMove) -> object: ...


@runtime_checkable
class PlannerPort(Protocol):
    async def plan(self, supervised_command: object) -> object: ...


@runtime_checkable
class ApplicationHostPort(Protocol):
    async def stop(self, exit_code: int) -> None:
        """Stop NSApplication on its main thread after all other teardown."""
