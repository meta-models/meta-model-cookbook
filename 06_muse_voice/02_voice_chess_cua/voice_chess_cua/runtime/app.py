# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Protocol, TypeVar

from voice_chess_cua.automation.move_executor import PreparedMove
from voice_chess_cua.domain.chess import VoiceAction, VoiceCommand
from voice_chess_cua.domain.game_state import MoveKind
from voice_chess_cua.events import (
    DiscardingRuntimeEventSink,
    RuntimeEvent,
    RuntimeEventSeverity,
    RuntimeEventSink,
)
from voice_chess_cua.events import (
    RuntimeStage as EventStage,
)
from voice_chess_cua.hud import (
    HUDPhase,
    HUDPresentation,
    HUDState,
    HUDUpdate,
    present_hud,
    reduce_hud,
)
from voice_chess_cua.macos.chess_state import ChessStateObservation
from voice_chess_cua.planning.schema import PlannerDecisionKind
from voice_chess_cua.planning.supervised_command import (
    SupervisedCommandText,
    _mint_supervised_command_text,
)
from voice_chess_cua.voice.asr_diagnostics import (
    ASRTransportError,
    safe_transport_diagnostics,
)
from voice_chess_cua.voice.pcm import normalized_pcm16le_rms

from .ports import (
    ApplicationHostPort,
    ASRPort,
    AudioPort,
    ChessApplicationPort,
    CredentialPort,
    FinalTranscript,
    GameStateObserverPort,
    OverlayPort,
    PartialTranscript,
    PermissionPort,
    PlannerPort,
    PreparedMoveExecutorPort,
    RuntimeCredentials,
    SettingsPort,
    SnapshotProbePort,
    SpeechEnded,
    SpeechStarted,
    SupervisedFinalTranscript,
    TrackingFailureReason,
    TrackingPort,
    TrackingStatus,
    VoiceLifecycle,
    VoiceLifecycleEvent,
    VoiceWorkerFailure,
)

BUSY_REARM_SILENCE_FRAMES = 6
BUSY_REARM_SILENCE_RMS = 0.01


class HostedRuntime(Protocol):
    async def run_until_stopped(self) -> int: ...

    async def shutdown(self, *, exit_code: int) -> int: ...


class RuntimeLifecycle(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    LISTENING = "listening"
    STOPPING = "stopping"
    FAILED = "failed"


class RuntimeExitCode(int, Enum):
    SUCCESS = 0
    CONFIGURATION = 3
    PERMISSION = 4
    CHESS_UNAVAILABLE = 5
    AUDIO_OR_ASR = 6
    COMMAND = 7
    AUTOMATION = 8
    INTERNAL_ERROR = 70


class RuntimeStage(StrEnum):
    SETTINGS = "settings"
    CREDENTIALS = "credentials"
    PERMISSIONS = "permissions"
    CHESS = "chess"
    TRACKING = "tracking"
    ASR = "asr"
    AUDIO = "audio"
    PLANNER = "planner"
    AUTOMATION = "automation"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    stage: RuntimeStage
    error: BaseException
    exit_code: int


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    settings: SettingsPort
    credentials: CredentialPort
    permissions: PermissionPort
    chess: ChessApplicationPort
    tracking: TrackingPort
    overlay: OverlayPort
    asr: ASRPort
    audio: AudioPort
    planner: PlannerPort
    application_host: ApplicationHostPort
    snapshot_probe: SnapshotProbePort
    move_executor: PreparedMoveExecutorPort
    notices: RuntimeEventSink = field(default_factory=DiscardingRuntimeEventSink)
    game_state: GameStateObserverPort | None = None


class RuntimeStartupError(RuntimeError):
    def __init__(self, failure: RuntimeFailure) -> None:
        super().__init__(
            f"runtime startup failed during {failure.stage.value}: {failure.error}"
        )
        self.failure = failure


class RuntimeCompositionError(RuntimeError):
    """Raised until the application supplies the live adapter factory."""


class BoardReadinessTimedOutError(RuntimeError):
    """Raised when no supported stable Chess board can present the overlay."""


T = TypeVar("T")


class VoiceCUARuntime:
    """Pure-async coordinator for one Voice CUA listening session.

    Native adapters own their thread-affinity rules. In particular, overlay and
    application-host methods must marshal their work to the AppKit main thread.
    """

    def __init__(
        self,
        dependencies: RuntimeDependencies,
        *,
        planning_timeout: float = 65.0,
        graceful_asr_close_timeout: float = 6.0,
        graceful_audio_drain_timeout: float = 2.0,
        board_readiness_timeout: float | None = None,
        dry_run: bool = False,
    ) -> None:
        if planning_timeout <= 0:
            raise ValueError("planning_timeout must be positive")
        if graceful_asr_close_timeout < 0:
            raise ValueError("graceful_asr_close_timeout must not be negative")
        if graceful_audio_drain_timeout < 0:
            raise ValueError("graceful_audio_drain_timeout must not be negative")
        if board_readiness_timeout is not None and board_readiness_timeout <= 0:
            raise ValueError("board_readiness_timeout must be positive when enabled")
        self._deps = dependencies
        self._planning_timeout = planning_timeout
        self._graceful_asr_close_timeout = graceful_asr_close_timeout
        self._graceful_audio_drain_timeout = graceful_audio_drain_timeout
        self._board_readiness_timeout = board_readiness_timeout
        self._dry_run = dry_run
        self._lifecycle = RuntimeLifecycle.STOPPED
        self._exit_code = int(RuntimeExitCode.SUCCESS)
        self._failure: RuntimeFailure | None = None
        self._settings: object | None = None
        self._credentials: RuntimeCredentials | None = None
        self._generation = 0
        self._planning_generation = 0
        self._seen_final_turns: set[str] = set()
        self._seen_partial_turns: set[str] = set()
        self._current_asr_generation: int | None = None
        self._busy_started_turns: set[tuple[int, str]] = set()
        self._process_identifier: int | None = None
        self._overlay_visible = False
        self._tracking_failure_reason: TrackingFailureReason | None = None
        self._stable_window_id: int | None = None
        self._hud_warning_active = False
        self._board_ready = asyncio.Event()
        self._hud = HUDState()
        self._pending_hud_presentation: HUDPresentation | None = None
        self._hud_drain_task: asyncio.Task[None] | None = None
        self._observed_game_number: int | None = None
        self._game_state_ready = False
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._command_tasks: set[asyncio.Task[None]] = set()
        self._planning_task: asyncio.Task[None] | None = None
        self._execution_task: asyncio.Task[object] | None = None
        self._execution_committed = False
        self._busy_audio_observed = False
        self._busy_rearm_silence_frames = 0
        self._startup_task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[int] | None = None
        self._stopped = asyncio.Event()
        self._stopped.set()

    @property
    def lifecycle(self) -> RuntimeLifecycle:
        return self._lifecycle

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def failure(self) -> RuntimeFailure | None:
        return self._failure

    @property
    def _transaction_busy(self) -> bool:
        return (
            self._planning_task is not None and not self._planning_task.done()
        ) or self._execution_committed

    async def start(self) -> None:
        if self._lifecycle is RuntimeLifecycle.STARTING:
            if self._startup_task is not None:
                await asyncio.shield(self._startup_task)
            return
        if self._lifecycle is RuntimeLifecycle.LISTENING:
            return
        if self._lifecycle is RuntimeLifecycle.STOPPING:
            raise RuntimeError("runtime is stopping")

        self._shutdown_task = None
        self._failure = None
        self._exit_code = int(RuntimeExitCode.SUCCESS)
        self._seen_final_turns.clear()
        self._seen_partial_turns.clear()
        self._current_asr_generation = None
        self._busy_started_turns.clear()
        self._busy_audio_observed = False
        self._busy_rearm_silence_frames = 0
        self._process_identifier = None
        self._observed_game_number = None
        self._game_state_ready = False
        self._overlay_visible = False
        self._board_ready.clear()
        self._pending_hud_presentation = None
        self._hud = reduce_hud(self._hud, HUDUpdate.starting())
        await self._render_hud()
        self._generation += 1
        generation = self._generation
        self._lifecycle = RuntimeLifecycle.STARTING
        self._stopped.clear()

        startup_task = asyncio.create_task(
            self._start_generation(generation),
            name=f"voice-cua-startup-{generation}",
        )
        self._startup_task = startup_task
        startup_task.add_done_callback(self._startup_finished)
        try:
            await asyncio.shield(startup_task)
        except asyncio.CancelledError:
            if (
                startup_task.cancelled()
                and self._lifecycle is RuntimeLifecycle.STOPPING
            ):
                return
            raise

    async def run_until_stopped(self) -> int:
        if self._lifecycle is RuntimeLifecycle.STOPPED and self._stopped.is_set():
            try:
                await self.start()
            except RuntimeStartupError:
                return self._exit_code
        await self._stopped.wait()
        return self._exit_code

    async def shutdown(
        self,
        *,
        exit_code: int | RuntimeExitCode | None = None,
        send_end_stream: bool = True,
    ) -> int:
        if self._shutdown_task is not None:
            return await asyncio.shield(self._shutdown_task)

        task = asyncio.create_task(
            self._shutdown(
                requested_exit_code=None if exit_code is None else int(exit_code),
                send_end_stream=send_end_stream,
            ),
            name="voice-cua-shutdown",
        )
        self._shutdown_task = task
        return await asyncio.shield(task)

    async def report_fatal(
        self,
        stage: RuntimeStage,
        error: BaseException,
        *,
        exit_code: int | RuntimeExitCode | None = None,
    ) -> int:
        self._record_fatal(stage, error, exit_code=exit_code)
        return await self.shutdown(exit_code=self._exit_code, send_end_stream=False)

    async def _start_generation(self, generation: int) -> None:
        stage = RuntimeStage.SETTINGS
        try:
            self._tracking_failure_reason = None
            self._stable_window_id = None
            self._hud_warning_active = False
            self._settings = await self._deps.settings.load_validated()
            self._ensure_active_generation(generation)
            self._emit(stage="startup", event="configuration_loaded")

            stage = RuntimeStage.CREDENTIALS
            credentials = await self._deps.credentials.load_runtime_credentials()
            self._validate_credentials(credentials)
            self._credentials = credentials
            self._ensure_active_generation(generation)
            self._emit(
                stage="credentials",
                event="loaded",
                fields={"model_api_key_present": True},
            )

            stage = RuntimeStage.PERMISSIONS
            await self._deps.permissions.verify_required()
            self._ensure_active_generation(generation)
            self._emit(stage="permissions", event="verified")

            stage = RuntimeStage.CHESS
            chess_status = await self._deps.chess.activate()
            self._ensure_active_generation(generation)
            self._emit(stage="chess", event="active")
            process_identifier = getattr(chess_status, "process_identifier", None)
            if isinstance(process_identifier, int) and not isinstance(
                process_identifier, bool
            ):
                self._process_identifier = process_identifier
            if self._deps.game_state is not None and isinstance(
                process_identifier, int
            ):
                self._deps.game_state.reset()
                self._start_worker(
                    "game-state",
                    self._run_game_state_updates(generation, process_identifier),
                    RuntimeStage.TRACKING,
                    fatal=False,
                )

            stage = RuntimeStage.TRACKING
            await self._deps.tracking.start(generation=generation)
            self._ensure_active_generation(generation)
            self._emit(stage="tracking", event="started")
            self._start_worker(
                "tracking",
                self._run_tracking_updates(generation),
                RuntimeStage.TRACKING,
            )
            if self._board_readiness_timeout is not None:
                self._emit(stage="tracking", event="waiting_for_board")
                try:
                    async with asyncio.timeout(self._board_readiness_timeout):
                        await self._board_ready.wait()
                except TimeoutError as error:
                    raise BoardReadinessTimedOutError(
                        "A supported stable Apple Chess board was not ready before timeout."
                    ) from error
                self._ensure_active_generation(generation)

            stage = RuntimeStage.ASR
            assert self._settings is not None
            await self._deps.asr.connect(
                settings=self._settings,
                access_token=credentials.model_api_key,
            )
            self._ensure_active_generation(generation)
            self._emit(stage="asr", event="connected")
            self._start_worker(
                "voice", self._run_voice_events(generation), RuntimeStage.ASR
            )

            stage = RuntimeStage.AUDIO
            await self._deps.audio.start()
            self._ensure_active_generation(generation)
            self._emit(stage="audio", event="capture_started")
            self._start_worker(
                "audio", self._run_audio_frames(generation), RuntimeStage.AUDIO
            )

            self._lifecycle = RuntimeLifecycle.LISTENING
            await self._update_hud(HUDUpdate.listening())
            self._emit(stage="startup", event="listening")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure = RuntimeFailure(
                stage, error, int(self._exit_code_for_stage(stage))
            )
            self._failure = failure
            self._exit_code = failure.exit_code
            self._lifecycle = RuntimeLifecycle.FAILED
            self._emit(
                stage="startup",
                event="failed",
                severity="error",
                fields=_safe_failure_fields(stage, error),
            )
            # Cleanup runs in its own task; remove this task from the cancellation
            # target first so the classified startup exception reaches the caller.
            self._startup_task = None
            await self.shutdown(exit_code=failure.exit_code, send_end_stream=False)
            raise RuntimeStartupError(failure) from error

    async def _run_tracking_updates(self, generation: int) -> None:
        async for update in self._deps.tracking.updates():
            self._ensure_active_generation(generation)
            if (
                update.generation == generation
                and update.status is TrackingStatus.STABLE
                and update.detection is not None
            ):
                presented = await self._deps.overlay.show_stable(update.detection)
                await self._update_hud(HUDUpdate(board_available=presented))
                if presented and not self._overlay_visible:
                    self._emit(stage="overlay", event="shown")
                elif not presented and self._overlay_visible:
                    self._emit(stage="overlay", event="hidden")
                self._overlay_visible = presented
                if presented:
                    self._board_ready.set()
                if self._tracking_failure_reason is not None:
                    self._emit(
                        stage="tracking",
                        event="recovered",
                        fields={"reason": self._tracking_failure_reason.value},
                    )
                    self._tracking_failure_reason = None
                window_id = getattr(update.detection, "source_window_id", None)
                stable_window_id = (
                    window_id
                    if isinstance(window_id, int) and not isinstance(window_id, bool)
                    else None
                )
                if presented and stable_window_id != self._stable_window_id:
                    fields: dict[str, str | float | bool] = {"method": "calibrated"}
                    if stable_window_id is not None:
                        fields["window_id"] = float(stable_window_id)
                    self._emit(stage="tracking", event="board_stable", fields=fields)
                self._stable_window_id = stable_window_id if presented else None
            else:
                if (
                    update.status is TrackingStatus.FAILED
                    and update.failure_reason is not None
                    and update.failure_reason != self._tracking_failure_reason
                ):
                    self._tracking_failure_reason = update.failure_reason
                    self._emit(
                        stage="tracking",
                        event="failed",
                        severity="warning",
                        fields={"reason": update.failure_reason.value},
                    )
                clear_board = getattr(self._deps.overlay, "clear_board", None)
                if callable(clear_board):
                    await clear_board()
                else:
                    await self._deps.overlay.hide()
                await self._update_hud(HUDUpdate(board_available=False))
                if self._overlay_visible:
                    self._emit(stage="overlay", event="board_cleared")
                self._overlay_visible = False
                self._stable_window_id = None

    async def _run_game_state_updates(
        self,
        generation: int,
        process_identifier: int,
    ) -> None:
        observer = self._deps.game_state
        if observer is None:
            return
        while True:
            try:
                async for value in observer.observations(process_identifier):
                    self._ensure_active_generation(generation)
                    if not isinstance(value, ChessStateObservation):
                        raise TypeError("unsupported Chess state observation")
                    new_game = self._observed_game_number != value.title.game_number
                    self._observed_game_number = value.title.game_number
                    turn = (
                        value.title.outcome or "Unknown"
                        if value.title.side_to_move is None
                        else f"{value.title.side_to_move.value.title()} to move"
                    )
                    update = HUDUpdate(
                        turn=turn,
                        last_move=(
                            "No move yet" if new_game else self._last_move_text(value)
                        ),
                    )
                    await self._update_hud(update)
                    if not self._game_state_ready:
                        self._game_state_ready = True
                        self._emit(stage="tracking", event="game_state_ready")
                    if value.inferred_move is not None:
                        if (
                            value.inferred_move.is_available
                            and value.inferred_move.move is not None
                        ):
                            self._emit(
                                stage="tracking",
                                event="move_observed",
                                fields={
                                    "source": value.inferred_move.move.source.notation,
                                    "destination": value.inferred_move.move.destination.notation,
                                },
                            )
                        await self._update_hud(self._idle_hud_update())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - AX display observation is nonfatal.
                await self._update_hud(
                    HUDUpdate(turn="Unknown", last_move="Unavailable")
                )
                if self._game_state_ready:
                    self._game_state_ready = False
                    self._emit(
                        stage="tracking",
                        event="game_state_unavailable",
                        severity="warning",
                    )
                await asyncio.sleep(0.5)

    def _last_move_text(self, observation: ChessStateObservation) -> str:
        inferred = observation.inferred_move
        if inferred is None:
            return self._hud.last_move
        if inferred.kind is MoveKind.UNAVAILABLE or inferred.move is None:
            return "Unavailable"
        moved_piece = inferred.moved_piece
        mover = "Unknown" if moved_piece is None else moved_piece.color.value.title()
        return f"{mover}: {inferred.move.source.notation} -> {inferred.move.destination.notation}"

    async def _run_voice_events(self, generation: int) -> None:
        async for event in self._deps.asr.events():
            self._ensure_active_generation(generation)
            if isinstance(event, VoiceLifecycleEvent):
                await self._handle_voice_lifecycle(event)
                continue
            if isinstance(event, VoiceWorkerFailure):
                raise event.error
            if isinstance(event, SpeechStarted):
                asr_generation = self._current_asr_generation
                if asr_generation is not None and self._transaction_busy:
                    self._busy_started_turns.add((asr_generation, event.turn_id))
                await self._update_hud(HUDUpdate.hearing())
                self._emit(stage="asr", event="speech_started")
                continue
            if isinstance(event, SpeechEnded):
                await self._update_hud(HUDUpdate.finalizing())
                self._emit(stage="asr", event="speech_ended")
                continue
            if isinstance(event, PartialTranscript):
                if event.turn_id in self._seen_final_turns:
                    continue
                if self._hud.phase not in {
                    HUDPhase.HEARING_SPEECH,
                    HUDPhase.FINALIZING,
                }:
                    await self._update_hud(HUDUpdate.hearing())
                self._offer_hud_update(HUDUpdate.partial(event.transcript))
                if event.turn_id not in self._seen_partial_turns:
                    self._seen_partial_turns.add(event.turn_id)
                    self._emit(stage="asr", event="partial_received")
                continue
            if isinstance(event, SupervisedFinalTranscript):
                await self._handle_supervised_final(event, generation)
                continue
            if isinstance(event, FinalTranscript):
                self._emit(
                    stage="asr",
                    event="unqualified_final_ignored",
                    severity="warning",
                )
                continue
            raise TypeError(f"unsupported voice event: {type(event).__name__}")

    async def _handle_supervised_final(
        self,
        event: SupervisedFinalTranscript,
        runtime_generation: int,
    ) -> None:
        turn_key = (event.generation, event.turn_id)
        busy_started = turn_key in self._busy_started_turns
        self._busy_started_turns.discard(turn_key)
        if self._lifecycle is not RuntimeLifecycle.LISTENING:
            return
        if event.generation != self._current_asr_generation:
            self._emit(stage="asr", event="stale_final_ignored", severity="warning")
            return
        if event.turn_id in self._seen_final_turns:
            return
        self._seen_final_turns.add(event.turn_id)
        self._seen_partial_turns.discard(event.turn_id)
        await self._update_hud(HUDUpdate.heard(event.transcript))
        self._emit(stage="asr", event="final_received")
        if not event.command_eligible:
            self._emit(stage="command-admission", event="ineligible_final_ignored")
            return
        if busy_started or self._transaction_busy:
            self._emit(stage="command-admission", event="ignored_while_busy")
            return
        if not event.transcript.strip():
            self._emit(stage="command-admission", event="empty_final_ignored")
            await self._update_hud(self._idle_hud_update())
            return
        supervised_command = _mint_supervised_command_text(
            runtime_generation=runtime_generation,
            asr_generation=event.generation,
            turn_id=event.turn_id,
            command_text=event.transcript,
        )
        self._emit(stage="command-admission", event="command_admitted")
        self._start_command_task(supervised_command, runtime_generation)

    async def _handle_voice_lifecycle(self, event: VoiceLifecycleEvent) -> None:
        fields = {"generation": float(event.generation)}
        if event.status is VoiceLifecycle.RECONNECTING:
            await self._update_hud(HUDUpdate.reconnecting())
            self._emit(stage="asr", event="reconnecting", fields=fields)
            return
        if event.status is not VoiceLifecycle.READY:
            raise TypeError(f"unsupported voice lifecycle: {event.status!r}")
        self._current_asr_generation = event.generation
        self._seen_final_turns.clear()
        self._seen_partial_turns.clear()
        self._busy_started_turns = {
            key for key in self._busy_started_turns if key[0] >= event.generation
        }
        if not self._transaction_busy:
            await self._update_hud(HUDUpdate.fresh_voice_session())
            await self._update_hud(self._idle_hud_update())
        self._emit(stage="asr", event="session_ready", fields=fields)

    async def _run_audio_frames(self, generation: int) -> None:
        reported_first_frame = False
        async for frame in self._deps.audio.frames():
            self._ensure_active_generation(generation)
            level = normalized_pcm16le_rms(frame)
            self._offer_hud_update(HUDUpdate.waveform(level))
            if self._transaction_busy:
                self._busy_audio_observed = True
                self._busy_rearm_silence_frames = 0
                continue
            if self._busy_audio_observed:
                if level <= BUSY_REARM_SILENCE_RMS:
                    self._busy_rearm_silence_frames += 1
                else:
                    self._busy_rearm_silence_frames = 0
                if self._busy_rearm_silence_frames < BUSY_REARM_SILENCE_FRAMES:
                    continue
                self._busy_audio_observed = False
                self._busy_rearm_silence_frames = 0
                continue
            await self._deps.asr.send_audio(frame)
            if not reported_first_frame:
                reported_first_frame = True
                self._emit(
                    stage="audio",
                    event="frame_forwarded",
                    fields={"bytes": float(len(frame))},
                )

    async def _plan_and_dispatch(
        self,
        supervised_command: SupervisedCommandText,
        generation: int,
        planning_generation: int,
    ) -> None:
        credentials = self._credentials
        if credentials is None:
            return
        try:
            await self._plan_and_execute_move(
                supervised_command,
                generation,
                planning_generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - planner/adapter failures are contained.
            self._emit(
                stage="planner",
                event="parse_failed",
                severity="error",
                fields={"category": type(error).__name__},
            )
            await self._update_hud(HUDUpdate.failed("Move failed"))

    async def _plan_and_execute_move(
        self,
        supervised_command: SupervisedCommandText,
        generation: int,
        planning_generation: int,
    ) -> None:
        if supervised_command.runtime_generation != generation:
            raise asyncio.CancelledError
        asr_generation = supervised_command.asr_generation
        baseline = await self._snapshot()
        self._ensure_current_planning(generation, planning_generation, asr_generation)
        await self._update_hud(HUDUpdate(phase=HUDPhase.PLANNING))
        self._emit(stage="planner", event="request_started")
        decision = await asyncio.wait_for(
            self._deps.planner.plan(supervised_command),
            timeout=self._planning_timeout,
        )
        self._ensure_current_planning(generation, planning_generation, asr_generation)
        post_planning = await self._snapshot()
        self._ensure_current_planning(generation, planning_generation, asr_generation)
        if baseline != post_planning:
            self._emit(
                stage="cua", event="board_changed_before_prepare", severity="warning"
            )
            await self._update_hud(HUDUpdate.failed("Board changed"))
            return
        if getattr(decision, "kind", None) is not PlannerDecisionKind.COMMAND:
            self._emit(stage="planner", event="no_move")
            await self._update_hud(self._idle_hud_update())
            return
        command = getattr(decision, "command", None)
        if (
            not isinstance(command, VoiceCommand)
            or command.action is not VoiceAction.MOVE
            or command.chess_move is None
        ):
            self._emit(stage="planner", event="non_move_rejected", severity="warning")
            await self._update_hud(self._idle_hud_update())
            return
        move_executor = self._deps.move_executor
        prepared = await move_executor.prepare(command.chess_move)
        self._ensure_current_planning(generation, planning_generation, asr_generation)
        if not isinstance(
            prepared, PreparedMove
        ) or not self._prepared_matches_snapshot(
            prepared,
            baseline,
        ):
            self._emit(
                stage="cua", event="prepared_baseline_changed", severity="warning"
            )
            await self._update_hud(HUDUpdate.failed("Board changed"))
            return
        self._emit(
            stage="planner",
            event="command_ready",
            fields={
                "action": "move",
                "source": command.chess_move.source.notation,
                "destination": command.chess_move.destination.notation,
                "dry_run": self._dry_run,
            },
        )
        if self._dry_run:
            self._emit(
                stage="cua",
                event="dry_run_validated",
                fields={
                    "source": command.chess_move.source.notation,
                    "destination": command.chess_move.destination.notation,
                },
            )
            await self._update_hud(self._idle_hud_update())
            return

        await self._update_hud(HUDUpdate(phase=HUDPhase.MOVING))
        self._execution_committed = True
        execution = asyncio.create_task(
            move_executor.execute_prepared(prepared),
            name=f"voice-cua-execution-{generation}-{planning_generation}",
        )
        self._execution_task = execution
        try:
            await asyncio.shield(execution)
        except asyncio.CancelledError:
            while not execution.done():
                try:
                    await asyncio.shield(execution)
                except asyncio.CancelledError:
                    continue
            execution.result()
            raise
        finally:
            if self._execution_task is execution:
                self._execution_task = None
        if self._deps.game_state is not None:
            self._deps.game_state.confirm_local_move(command.chess_move)
        self._emit(
            stage="cua",
            event="move_confirmed",
            fields={
                "source": command.chess_move.source.notation,
                "destination": command.chess_move.destination.notation,
            },
        )
        await self._update_hud(HUDUpdate(phase=HUDPhase.WAITING_FOR_CHESS))

    async def _snapshot(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        snapshot_probe = self._deps.snapshot_probe
        process_identifier = self._process_identifier
        if process_identifier is None:
            raise RuntimeError(
                "automatic move execution requires a Chess snapshot probe"
            )
        title, squares = await snapshot_probe.game_snapshot(process_identifier)
        return title, tuple(
            sorted(
                (str(square).lower(), str(value)) for square, value in squares.items()
            )
        )

    @staticmethod
    def _prepared_matches_snapshot(
        prepared: PreparedMove,
        snapshot: tuple[str, tuple[tuple[str, str], ...]],
    ) -> bool:
        prepared_snapshot = tuple(
            sorted(
                (square.notation.lower(), description)
                for square, description in prepared.square_snapshot
            )
        )
        return (prepared.ax_title, prepared_snapshot) == snapshot

    def _ensure_current_planning(
        self,
        generation: int,
        planning_generation: int,
        asr_generation: int,
    ) -> None:
        self._ensure_active_generation(generation)
        if (
            planning_generation != self._planning_generation
            or asr_generation != self._deps.asr.generation
        ):
            raise asyncio.CancelledError

    def _start_worker(
        self,
        name: str,
        coroutine: Coroutine[Any, Any, None],
        stage: RuntimeStage,
        *,
        fatal: bool = True,
    ) -> None:
        task = asyncio.create_task(coroutine, name=f"voice-cua-{name}")
        self._workers[name] = task

        def worker_finished(completed: asyncio.Task[None]) -> None:
            self._worker_finished(name, stage, completed, fatal=fatal)

        task.add_done_callback(worker_finished)

    def _worker_finished(
        self,
        name: str,
        stage: RuntimeStage,
        task: asyncio.Task[None],
        *,
        fatal: bool,
    ) -> None:
        if task.cancelled():
            if self._workers.get(name) is task:
                self._workers.pop(name, None)
            return

        error = task.exception()
        if self._workers.get(name) is task:
            self._workers.pop(name, None)
        if self._lifecycle is RuntimeLifecycle.STOPPED or not fatal:
            return
        if error is None:
            if self._lifecycle in {RuntimeLifecycle.STOPPING, RuntimeLifecycle.FAILED}:
                return
            error = RuntimeError(f"{name} worker stopped unexpectedly")
        self._record_fatal(stage, error)
        asyncio.create_task(
            self.shutdown(exit_code=self._exit_code, send_end_stream=False),
            name=f"voice-cua-fatal-{name}",
        )

    def _startup_finished(self, task: asyncio.Task[None]) -> None:
        if self._startup_task is task:
            self._startup_task = None
        if not task.cancelled():
            task.exception()

    def _record_fatal(
        self,
        stage: RuntimeStage,
        error: BaseException,
        *,
        exit_code: int | RuntimeExitCode | None = None,
    ) -> None:
        if self._failure is not None:
            return
        classified_code = (
            self._exit_code_for_stage(stage) if exit_code is None else int(exit_code)
        )
        self._failure = RuntimeFailure(stage, error, classified_code)
        self._exit_code = classified_code
        if self._lifecycle is not RuntimeLifecycle.STOPPING:
            self._lifecycle = RuntimeLifecycle.FAILED
        self._emit(
            stage=stage.value,
            event="fatal",
            severity="error",
            fields=_safe_failure_fields(stage, error),
        )

    def _start_command_task(
        self, supervised_command: SupervisedCommandText, generation: int
    ) -> None:
        if self._transaction_busy:
            self._emit(stage="command-admission", event="ignored_while_busy")
            return
        self._planning_generation += 1
        planning_generation = self._planning_generation
        self._busy_audio_observed = True
        self._busy_rearm_silence_frames = 0
        self._deps.audio.set_transaction_busy(True)
        task = asyncio.create_task(
            self._plan_and_dispatch(
                supervised_command, generation, planning_generation
            ),
            name=f"voice-cua-command-{generation}-{planning_generation}",
        )
        self._planning_task = task
        self._command_tasks.add(task)
        task.add_done_callback(self._command_task_finished)

    def _command_task_finished(self, task: asyncio.Task[None]) -> None:
        self._command_tasks.discard(task)
        if self._planning_task is task:
            self._planning_task = None
            self._execution_committed = False
            self._deps.audio.set_transaction_busy(False)

    async def _shutdown(
        self,
        *,
        requested_exit_code: int | None,
        send_end_stream: bool,
    ) -> int:
        if requested_exit_code is not None and self._failure is None:
            self._exit_code = requested_exit_code
        self._lifecycle = RuntimeLifecycle.STOPPING
        await self._update_hud(HUDUpdate(phase=HUDPhase.STOPPING))
        self._emit(stage="shutdown", event="started")

        # Invalidation happens before cancellation so late results fail closed.
        self._generation += 1
        self._planning_generation += 1
        self._credentials = None
        self._settings = None
        self._current_asr_generation = None
        self._busy_started_turns.clear()

        current_task = asyncio.current_task()
        startup_task = self._startup_task
        if startup_task is not None and startup_task is not current_task:
            startup_task.cancel()
            await self._await_cancelled(startup_task)

        if self._execution_committed:
            await asyncio.gather(*self._command_tasks, return_exceptions=True)
        else:
            await self._cancel_and_await(self._command_tasks)
        self._planning_task = None
        self._execution_task = None

        await self._best_effort(self._deps.audio.stop)
        audio_worker = self._workers.pop("audio", None)
        if audio_worker is not None:
            if send_end_stream and self._failure is None:
                completed = await self._await_worker_bounded(
                    audio_worker,
                    RuntimeStage.AUDIO,
                    self._graceful_audio_drain_timeout,
                )
                if not completed:
                    await self._cancel_worker(audio_worker, RuntimeStage.AUDIO)
            else:
                await self._cancel_worker(audio_worker, RuntimeStage.AUDIO)
        await self._best_effort_bounded(
            self._deps.audio.drain,
            self._graceful_audio_drain_timeout,
        )

        if send_end_stream and self._failure is None:
            await self._best_effort(self._deps.asr.end_stream)
            await self._best_effort(
                lambda: self._deps.asr.wait_closed(self._graceful_asr_close_timeout)
            )
        await self._best_effort(self._deps.asr.disconnect)
        voice_worker = self._workers.pop("voice", None)
        if voice_worker is not None:
            await self._cancel_worker(voice_worker, RuntimeStage.ASR)
        await self._stop_hud_drain()

        self._hud = HUDState(revision=self._hud.revision + 1)
        await self._best_effort(self._deps.tracking.stop)
        tracking_worker = self._workers.pop("tracking", None)
        if tracking_worker is not None:
            await self._cancel_worker(tracking_worker, RuntimeStage.TRACKING)

        for worker in tuple(self._workers.values()):
            worker.cancel()
        await self._cancel_and_await(set(self._workers.values()))
        self._workers.clear()

        await self._best_effort(self._deps.overlay.hide)
        await self._best_effort(self._deps.overlay.destroy)
        await self._best_effort(
            lambda: self._deps.application_host.stop(self._exit_code)
        )

        if self._failure is None:
            self._lifecycle = RuntimeLifecycle.STOPPED
        else:
            self._lifecycle = RuntimeLifecycle.FAILED
        self._emit(stage="shutdown", event="completed")
        self._stopped.set()
        return self._exit_code

    def _idle_hud_update(self) -> HUDUpdate:
        return HUDUpdate(phase=HUDPhase.LISTENING)

    async def _update_hud(self, update: HUDUpdate) -> None:
        candidate = reduce_hud(self._hud, update)
        if (
            candidate.phase == self._hud.phase
            and candidate.transcript == self._hud.transcript
            and candidate.partial_transcript == self._hud.partial_transcript
            and candidate.waveform == self._hud.waveform
            and candidate.error_message == self._hud.error_message
            and candidate.turn == self._hud.turn
            and candidate.last_move == self._hud.last_move
            and candidate.board_available == self._hud.board_available
        ):
            return
        self._hud = candidate
        await self._render_hud()

    def _offer_hud_update(self, update: HUDUpdate) -> None:
        candidate = reduce_hud(self._hud, update)
        if (
            candidate.phase == self._hud.phase
            and candidate.transcript == self._hud.transcript
            and candidate.partial_transcript == self._hud.partial_transcript
            and candidate.waveform == self._hud.waveform
            and candidate.error_message == self._hud.error_message
            and candidate.turn == self._hud.turn
            and candidate.last_move == self._hud.last_move
            and candidate.board_available == self._hud.board_available
        ):
            return
        self._hud = candidate
        self._pending_hud_presentation = present_hud(candidate)
        task = self._hud_drain_task
        if task is None or task.done():
            self._hud_drain_task = asyncio.create_task(
                self._drain_hud_updates(),
                name="voice-cua-hud-drain",
            )

    async def _drain_hud_updates(self) -> None:
        try:
            while self._pending_hud_presentation is not None:
                presentation = self._pending_hud_presentation
                self._pending_hud_presentation = None
                update_hud = getattr(self._deps.overlay, "update_hud", None)
                if callable(update_hud):
                    try:
                        await update_hud(presentation)
                    except Exception:  # noqa: BLE001 - display failure is nonfatal.
                        self._record_hud_warning()
                    else:
                        self._hud_warning_active = False
        finally:
            if self._hud_drain_task is asyncio.current_task():
                self._hud_drain_task = None

    async def _stop_hud_drain(self) -> None:
        self._pending_hud_presentation = None
        task = self._hud_drain_task
        self._hud_drain_task = None
        if task is None or task.done():
            return
        task.cancel()
        await self._await_cancelled(task)

    async def _render_hud(self) -> None:
        update_hud = getattr(self._deps.overlay, "update_hud", None)
        if not callable(update_hud):
            return
        try:
            await update_hud(present_hud(self._hud))
        except Exception:  # noqa: BLE001 - display failure cannot affect safety.
            self._record_hud_warning()
        else:
            self._hud_warning_active = False

    def _record_hud_warning(self) -> None:
        if self._hud_warning_active:
            return
        self._hud_warning_active = True
        self._emit(
            stage="overlay",
            event="warning",
            severity="warning",
            fields={"category": "overlay_display", "reason": "hud_update_failed"},
        )

    async def _best_effort(self, operation: Callable[[], Awaitable[T]]) -> T | None:
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - shutdown continues after cleanup failure.
            if self._failure is None:
                self._failure = RuntimeFailure(
                    RuntimeStage.INTERNAL,
                    error,
                    int(RuntimeExitCode.INTERNAL_ERROR),
                )
                self._exit_code = self._failure.exit_code
                self._emit(
                    stage="shutdown",
                    event="cleanup_failed",
                    severity="error",
                    fields={"category": type(error).__name__},
                )
            return None

    async def _best_effort_bounded(
        self,
        operation: Callable[[], Awaitable[T]],
        timeout: float,
    ) -> T | None:
        try:
            async with asyncio.timeout(timeout):
                return await self._best_effort(operation)
        except TimeoutError:
            self._emit(
                stage="shutdown",
                event="cleanup_timed_out",
                severity="warning",
            )
            return None

    async def _await_worker_bounded(
        self,
        task: asyncio.Task[None],
        stage: RuntimeStage,
        timeout: float,
    ) -> bool:
        try:
            async with asyncio.timeout(timeout):
                await asyncio.shield(task)
        except TimeoutError:
            return False
        except asyncio.CancelledError as error:
            self._classify_worker_result(stage, error)
        except Exception as error:  # noqa: BLE001 - task result is classified below.
            self._classify_worker_result(stage, error)
        return True

    async def _await_worker(
        self,
        task: asyncio.Task[None],
        stage: RuntimeStage,
    ) -> None:
        results = await asyncio.gather(task, return_exceptions=True)
        self._classify_worker_result(stage, results[0])

    async def _cancel_worker(
        self,
        task: asyncio.Task[None],
        stage: RuntimeStage,
    ) -> None:
        if not task.done():
            task.cancel()
        results = await asyncio.gather(task, return_exceptions=True)
        self._classify_worker_result(stage, results[0])

    def _classify_worker_result(self, stage: RuntimeStage, result: object) -> None:
        if isinstance(result, BaseException) and not isinstance(
            result, asyncio.CancelledError
        ):
            self._record_fatal(stage, result)

    async def _cancel_and_await(self, tasks: set[asyncio.Task[None]]) -> None:
        if not tasks:
            return
        current_task = asyncio.current_task()
        task_list = tuple(task for task in tasks if task is not current_task)
        for task in task_list:
            task.cancel()
        if task_list:
            await asyncio.gather(*task_list, return_exceptions=True)
        tasks.difference_update(task_list)

    @staticmethod
    async def _await_cancelled(task: asyncio.Task[Any]) -> None:
        await asyncio.gather(task, return_exceptions=True)

    def _ensure_active_generation(self, generation: int) -> None:
        if generation != self._generation or self._lifecycle in {
            RuntimeLifecycle.STOPPING,
            RuntimeLifecycle.STOPPED,
            RuntimeLifecycle.FAILED,
        }:
            raise asyncio.CancelledError

    @staticmethod
    def _validate_credentials(credentials: RuntimeCredentials) -> None:
        if not credentials.model_api_key.strip():
            raise ValueError("Model API key is missing")

    @staticmethod
    def _exit_code_for_stage(stage: RuntimeStage) -> RuntimeExitCode:
        return {
            RuntimeStage.SETTINGS: RuntimeExitCode.CONFIGURATION,
            RuntimeStage.CREDENTIALS: RuntimeExitCode.CONFIGURATION,
            RuntimeStage.PERMISSIONS: RuntimeExitCode.PERMISSION,
            RuntimeStage.CHESS: RuntimeExitCode.CHESS_UNAVAILABLE,
            RuntimeStage.TRACKING: RuntimeExitCode.CHESS_UNAVAILABLE,
            RuntimeStage.ASR: RuntimeExitCode.AUDIO_OR_ASR,
            RuntimeStage.AUDIO: RuntimeExitCode.AUDIO_OR_ASR,
            RuntimeStage.PLANNER: RuntimeExitCode.COMMAND,
            RuntimeStage.AUTOMATION: RuntimeExitCode.AUTOMATION,
            RuntimeStage.INTERNAL: RuntimeExitCode.INTERNAL_ERROR,
        }[stage]

    def _emit(
        self,
        *,
        stage: str,
        event: str,
        severity: str = "info",
        fields: dict[str, Any] | None = None,
    ) -> None:
        event_stage = {
            "settings": EventStage.STARTUP,
            "tracking": EventStage.VISION,
            "planner": EventStage.PLANNER,
            "automation": EventStage.CUA,
            "internal": EventStage.SHUTDOWN,
        }.get(stage)
        if event_stage is None:
            event_stage = EventStage(stage)
        try:
            self._deps.notices.emit(
                RuntimeEvent(
                    stage=event_stage,
                    event=event,
                    severity=RuntimeEventSeverity[severity.upper()],
                    fields=fields or {},
                )
            )
        except Exception:  # noqa: BLE001, S110 - observability cannot break lifecycle safety.
            pass


def _safe_failure_fields(
    stage: RuntimeStage,
    error: BaseException,
) -> dict[str, str | int]:
    fields: dict[str, str | int] = {
        "phase": stage.value,
        "category": type(error).__name__,
        "reason": _safe_failure_reason(stage, error),
    }
    if isinstance(error, ASRTransportError):
        fields.update(safe_transport_diagnostics(error))
    return fields


def _safe_failure_reason(stage: RuntimeStage, error: BaseException) -> str:
    if stage is RuntimeStage.TRACKING and isinstance(
        error, BoardReadinessTimedOutError
    ):
        return "board_not_ready"
    if stage is RuntimeStage.CHESS:
        name = type(error).__name__
        if "Unavailable" in name:
            return "chess_unavailable"
        if "TimedOut" in name:
            return "chess_activation_timed_out"
        return "chess_activation_failed"
    return f"{stage.value}_failed"


def build_live_runtime() -> HostedRuntime:
    """Construct the live runtime lazily without importing native frameworks."""

    from .services import build_live_runtime as compose_live_runtime

    return compose_live_runtime().runtime
