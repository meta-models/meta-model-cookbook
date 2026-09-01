# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from voice_chess_cua.automation.move_executor import PreparedMove
from voice_chess_cua.domain.chess import (
    BoardOrientation,
    ChessMove,
    ChessSquare,
    VoiceCommand,
)
from voice_chess_cua.domain.game_state import ChessGameState
from voice_chess_cua.domain.geometry import (
    BoardDetection,
    BoardGeometry,
    Point,
    Quad,
    Rect,
)
from voice_chess_cua.planning.schema import PlannerDecision
from voice_chess_cua.planning.supervised_command import SupervisedCommandText
from voice_chess_cua.runtime import (
    RuntimeCredentials,
    RuntimeDependencies,
    VoiceCUARuntime,
)
from voice_chess_cua.runtime.ports import (
    FinalTranscript,
    PartialTranscript,
    SupervisedFinalTranscript,
    TrackingFailureReason,
    TrackingStatus,
    TrackingUpdate,
    VoiceLifecycle,
    VoiceLifecycleEvent,
)
from voice_chess_cua.voice.asr_client import ASRTransportError
from voice_chess_cua.voice.asr_diagnostics import ASRTransportPhase

_STREAM_END = object()


async def eventually(predicate, *, turns: int = 200) -> None:
    for _ in range(turns):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


class QueueStream:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[object] = asyncio.Queue()

    def put(self, value: object) -> None:
        self.queue.put_nowait(value)

    async def iterate(self):
        while True:
            value = await self.queue.get()
            if value is _STREAM_END:
                return
            yield value


class SettingsFake:
    async def load_validated(self) -> object:
        return object()


class CredentialsFake:
    async def load_runtime_credentials(self) -> RuntimeCredentials:
        return RuntimeCredentials("meta-api-key")


class PermissionsFake:
    async def verify_required(self) -> None:
        return None


class ChessFake:
    async def activate(self) -> object:
        return SimpleNamespace(process_identifier=42, is_frontmost=True)


class TrackingFake:
    def __init__(self) -> None:
        self.stream = QueueStream()

    async def start(self, *, generation: int) -> None:
        del generation

    def updates(self):
        return self.stream.iterate()

    async def stop(self) -> None:
        self.stream.put(_STREAM_END)


class OverlayFake:
    async def show_stable(self, detection: object) -> bool:
        del detection
        return True

    async def update_hud(self, state: object) -> None:
        del state

    async def clear_board(self) -> None:
        return None

    async def hide(self) -> None:
        return None

    async def destroy(self) -> None:
        return None


class ASRFake:
    def __init__(self, connect_error: BaseException | None = None) -> None:
        self.stream = QueueStream()
        self.sent_audio: list[bytes] = []
        self.generation = 0
        self.connect_error = connect_error

    async def connect(self, *, settings: object, access_token: str) -> None:
        del settings
        assert access_token == "meta-api-key"
        if self.connect_error is not None:
            raise self.connect_error

    def events(self):
        return self.stream.iterate()

    async def send_audio(self, frame: bytes) -> None:
        self.sent_audio.append(frame)

    async def end_stream(self) -> None:
        return None

    async def wait_closed(self, timeout: float) -> bool:
        del timeout
        return True

    async def disconnect(self) -> None:
        self.stream.put(_STREAM_END)


class AudioFake:
    def __init__(self) -> None:
        self.stream = QueueStream()
        self.busy_states: list[bool] = []

    def set_transaction_busy(self, busy: bool) -> None:
        self.busy_states.append(busy)

    async def start(self) -> None:
        return None

    def frames(self):
        return self.stream.iterate()

    async def stop(self) -> None:
        self.stream.put(_STREAM_END)

    async def drain(self) -> None:
        return None


class PlannerFake:
    def __init__(self, decision: PlannerDecision) -> None:
        self.decision = decision
        self.requests: list[SupervisedCommandText] = []
        self.entered = asyncio.Event()
        self.block: asyncio.Event | None = None

    async def plan(self, supervised_command: object) -> object:
        assert isinstance(supervised_command, SupervisedCommandText)
        self.requests.append(supervised_command)
        self.entered.set()
        if self.block is not None:
            await self.block.wait()
        return self.decision


class SnapshotFake:
    def __init__(self, *, drift_after_first: bool = False) -> None:
        self.calls = 0
        self.drift_after_first = drift_after_first

    async def game_snapshot(self, process_identifier: int):
        assert process_identifier == 42
        self.calls += 1
        title = "Game 2" if self.drift_after_first and self.calls > 1 else "Game 1"
        return title, {
            square.notation.lower(): square.notation.lower()
            for square in ChessSquare.all()
        }


class ExecutorFake:
    def __init__(self) -> None:
        self.prepared: list[PreparedMove] = []
        self.executed: list[PreparedMove] = []
        self.execution_started = asyncio.Event()
        self.execution_release: asyncio.Event | None = None
        self.execution_cancelled = False
        self.returned = asyncio.Event()

    async def prepare(
        self,
        move: ChessMove,
        *,
        expires_at: float | None = None,
    ) -> PreparedMove:
        assert expires_at is None
        prepared = PreparedMove(
            move=move,
            detection=BoardDetection(
                BoardGeometry(
                    Quad(
                        Point(100, 100),
                        Point(900, 100),
                        Point(900, 900),
                        Point(100, 900),
                    ),
                    BoardOrientation.WHITE_BOTTOM,
                ),
                confidence=1.0,
                proposal_score=1.0,
                source_window_id=7,
            ),
            source=Point(450, 750),
            destination=Point(450, 550),
            process_identifier=42,
            window_id=7,
            window_frame=Rect(0, 0, 1_000, 1_000),
            ax_title="Game 1",
            square_snapshot=tuple(
                (square, square.notation.lower()) for square in ChessSquare.all()
            ),
            game_state=ChessGameState.empty(),
            tracking_generation=1,
        )
        self.prepared.append(prepared)
        return prepared

    async def execute_prepared(self, prepared: object) -> object:
        assert isinstance(prepared, PreparedMove)
        self.executed.append(prepared)
        self.execution_started.set()
        try:
            if self.execution_release is not None:
                await self.execution_release.wait()
        except asyncio.CancelledError:
            self.execution_cancelled = True
            raise
        self.returned.set()
        return SimpleNamespace(move=prepared.move)


class HostFake:
    async def stop(self, exit_code: int) -> None:
        del exit_code


class NoticeFake:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


@dataclass
class Scenario:
    runtime: VoiceCUARuntime
    asr: ASRFake
    planner: PlannerFake
    snapshots: SnapshotFake
    executor: ExecutorFake
    notices: NoticeFake


async def start_scenario(
    decision: PlannerDecision,
    *,
    drift_after_first: bool = False,
    dry_run: bool = False,
) -> Scenario:
    asr = ASRFake()
    planner = PlannerFake(decision)
    snapshots = SnapshotFake(drift_after_first=drift_after_first)
    executor = ExecutorFake()
    notices = NoticeFake()
    runtime = VoiceCUARuntime(
        RuntimeDependencies(
            settings=SettingsFake(),
            credentials=CredentialsFake(),
            permissions=PermissionsFake(),
            chess=ChessFake(),
            tracking=TrackingFake(),
            overlay=OverlayFake(),
            asr=asr,
            audio=AudioFake(),
            planner=planner,
            application_host=HostFake(),
            notices=notices,
            snapshot_probe=snapshots,
            move_executor=executor,
        ),
        dry_run=dry_run,
    )
    await runtime.start()
    asr.generation = 1
    asr.stream.put(VoiceLifecycleEvent(VoiceLifecycle.READY, 1))
    await eventually(lambda: runtime._current_asr_generation == 1)
    return Scenario(runtime, asr, planner, snapshots, executor, notices)


@pytest.mark.asyncio
async def test_asr_startup_failure_emits_safe_tls_diagnostics() -> None:
    tls_error = ssl.SSLCertVerificationError(1, "certificate detail with secret")
    transport_error = ASRTransportError(ASRTransportPhase.WEBSOCKET_CONNECT)
    transport_error.__cause__ = tls_error
    notices = NoticeFake()
    runtime = VoiceCUARuntime(
        RuntimeDependencies(
            settings=SettingsFake(),
            credentials=CredentialsFake(),
            permissions=PermissionsFake(),
            chess=ChessFake(),
            tracking=TrackingFake(),
            overlay=OverlayFake(),
            asr=ASRFake(transport_error),
            audio=AudioFake(),
            planner=PlannerFake(PlannerDecision.reject()),
            application_host=HostFake(),
            notices=notices,
            snapshot_probe=SnapshotFake(),
            move_executor=ExecutorFake(),
        )
    )

    with pytest.raises(Exception, match="startup failed"):
        await runtime.start()

    failure = next(
        event for event in notices.events if getattr(event, "event", None) == "failed"
    )
    fields = {field.key: field.rendered_value for field in failure.fields}
    assert fields == {
        "category": '"ASRTransportError"',
        "classification": '"tls_verification_failed"',
        "phase": '"asr"',
        "reason": '"websocket_connect_failed"',
        "transport": '"websocket_connect"',
    }
    rendered = " ".join(fields.values())
    assert "certificate detail" not in rendered
    assert "secret" not in rendered


@pytest.mark.asyncio
async def test_tracking_failures_are_deduplicated_and_recovery_is_reported() -> None:
    scenario = await start_scenario(move_decision())
    tracking = scenario.runtime._deps.tracking
    assert isinstance(tracking, TrackingFake)
    failed = TrackingUpdate(
        TrackingStatus.FAILED,
        generation=1,
        failure_reason=TrackingFailureReason.LAYOUT_MISMATCH,
    )
    tracking.stream.put(failed)
    tracking.stream.put(failed)
    await eventually(
        lambda: (
            sum(
                getattr(event, "event", None) == "failed"
                and any(
                    field.rendered_value == '"layout_mismatch"'
                    for field in getattr(event, "fields", ())
                )
                for event in scenario.notices.events
            )
            == 1
        )
    )
    tracking.stream.put(
        TrackingUpdate(
            TrackingStatus.FAILED,
            generation=1,
            failure_reason=TrackingFailureReason.CAPTURE_TIMEOUT,
        )
    )
    await eventually(
        lambda: (
            sum(
                getattr(event, "event", None) == "failed"
                for event in scenario.notices.events
            )
            == 2
        )
    )
    detection = BoardDetection(
        BoardGeometry(
            Quad(
                Point(100, 100),
                Point(900, 100),
                Point(900, 900),
                Point(100, 900),
            )
        ),
        0.99,
        1.0,
        source_window_id=7,
    )
    tracking.stream.put(TrackingUpdate(TrackingStatus.STABLE, 1, detection))
    await eventually(
        lambda: any(
            getattr(event, "event", None) == "recovered"
            for event in scenario.notices.events
        )
    )

    assert (
        sum(
            getattr(event, "event", None) == "failed"
            for event in scenario.notices.events
        )
        == 2
    )
    assert (
        sum(
            getattr(event, "event", None) == "board_stable"
            for event in scenario.notices.events
        )
        == 1
    )
    tracking.stream.put(TrackingUpdate(TrackingStatus.STABLE, 1, detection))
    await asyncio.sleep(0)
    assert (
        sum(
            getattr(event, "event", None) == "board_stable"
            for event in scenario.notices.events
        )
        == 1
    )
    await scenario.runtime.shutdown(send_end_stream=False)


def move_decision() -> PlannerDecision:
    return PlannerDecision.for_command(
        VoiceCommand.move(ChessMove(ChessSquare.parse("E2"), ChessSquare.parse("E4")))
    )


@pytest.mark.asyncio
async def test_supervised_final_automatically_executes_prepared_move_once() -> None:
    scenario = await start_scenario(move_decision())
    scenario.asr.stream.put(
        SupervisedFinalTranscript(1, "turn-1", "  Move E2 to E4, PLEASE!  ")
    )

    await eventually(
        lambda: any(
            getattr(event, "event", None) == "move_confirmed"
            for event in scenario.notices.events
        )
    )

    request = scenario.planner.requests[0]
    assert request.runtime_generation == 1
    assert request.asr_generation == 1
    assert request.turn_id == "turn-1"
    assert request.value == "  Move E2 to E4, PLEASE!  "
    assert scenario.snapshots.calls == 2
    assert len(scenario.executor.prepared) == 1
    assert scenario.executor.executed == scenario.executor.prepared
    assert any(
        getattr(event, "event", None) == "move_confirmed"
        for event in scenario.notices.events
    )
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_dry_run_prepares_but_never_consumes_the_move_capability() -> None:
    scenario = await start_scenario(move_decision(), dry_run=True)
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))

    await eventually(
        lambda: any(
            getattr(event, "event", None) == "dry_run_validated"
            for event in scenario.notices.events
        )
    )

    assert len(scenario.executor.prepared) == 1
    assert scenario.executor.executed == []
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_partials_raw_finals_non_moves_and_board_drift_never_execute() -> None:
    non_move = await start_scenario(PlannerDecision.reject())
    non_move.asr.stream.put(PartialTranscript("partial", "Move E2"))
    non_move.asr.stream.put(FinalTranscript("raw", "Move E2 to E4"))
    non_move.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move a pawn"))
    await eventually(lambda: len(non_move.planner.requests) == 1)
    await eventually(lambda: non_move.runtime._planning_task is None)
    assert non_move.executor.prepared == []
    assert non_move.executor.executed == []
    await non_move.runtime.shutdown(send_end_stream=False)

    drift = await start_scenario(move_decision(), drift_after_first=True)
    drift.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await eventually(lambda: drift.snapshots.calls == 2)
    await eventually(lambda: drift.runtime._planning_task is None)
    assert drift.executor.prepared == []
    assert drift.executor.executed == []
    await drift.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_non_command_voice_events_never_reach_planner() -> None:
    scenario = await start_scenario(move_decision())
    scenario.asr.stream.put(PartialTranscript("partial", "Move E2"))
    scenario.asr.stream.put(FinalTranscript("raw", "Move E2 to E4"))
    scenario.asr.stream.put(SupervisedFinalTranscript(2, "stale", "Move E2 to E4"))
    scenario.asr.stream.put(
        SupervisedFinalTranscript(
            1,
            "superseded",
            "Move E2 to E4",
            command_eligible=False,
        )
    )
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "empty", "  \t\n  "))

    await eventually(
        lambda: {"superseded", "empty"} <= scenario.runtime._seen_final_turns
    )

    assert scenario.planner.requests == []
    assert scenario.snapshots.calls == 0
    assert scenario.executor.prepared == []
    assert scenario.executor.executed == []
    assert {getattr(event, "event", None) for event in scenario.notices.events} >= {
        "unqualified_final_ignored",
        "stale_final_ignored",
        "ineligible_final_ignored",
        "empty_final_ignored",
    }
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_duplicate_supervised_final_reaches_planner_only_once() -> None:
    scenario = await start_scenario(PlannerDecision.reject())
    duplicate = SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4")
    scenario.asr.stream.put(duplicate)
    await eventually(lambda: len(scenario.planner.requests) == 1)
    await eventually(lambda: scenario.runtime._planning_task is None)

    scenario.asr.stream.put(duplicate)
    scenario.asr.stream.put(
        SupervisedFinalTranscript(
            1,
            "drain-marker",
            "ignored",
            command_eligible=False,
        )
    )
    await eventually(lambda: "drain-marker" in scenario.runtime._seen_final_turns)

    assert len(scenario.planner.requests) == 1
    assert scenario.planner.requests[0].value == "Move E2 to E4"
    assert scenario.executor.prepared == []
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_final_received_while_transaction_busy_is_not_queued() -> None:
    scenario = await start_scenario(PlannerDecision.reject())
    scenario.planner.block = asyncio.Event()
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.planner.entered.wait()

    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-2", "Move D2 to D4"))
    await eventually(lambda: "turn-2" in scenario.runtime._seen_final_turns)

    assert len(scenario.planner.requests) == 1
    assert scenario.planner.requests[0].turn_id == "turn-1"
    scenario.planner.block.set()
    await eventually(lambda: scenario.runtime._planning_task is None)
    assert scenario.executor.prepared == []
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_asr_generation_advance_before_ready_delivery_blocks_stale_plan() -> None:
    scenario = await start_scenario(move_decision())
    scenario.planner.block = asyncio.Event()
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.planner.entered.wait()

    scenario.asr.generation = 2
    scenario.planner.block.set()
    await eventually(lambda: scenario.runtime._planning_task is None)

    assert scenario.executor.prepared == []
    assert scenario.executor.executed == []
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_busy_started_turn_is_discarded_and_never_queued() -> None:
    scenario = await start_scenario(move_decision())
    scenario.executor.execution_release = asyncio.Event()
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.executor.execution_started.wait()

    from voice_chess_cua.runtime.ports import SpeechStarted

    scenario.asr.stream.put(SpeechStarted("turn-2"))
    await eventually(lambda: (1, "turn-2") in scenario.runtime._busy_started_turns)
    scenario.executor.execution_release.set()
    await eventually(lambda: scenario.runtime._planning_task is None)
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-2", "Move D2 to D4"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(scenario.planner.requests) == 1
    assert len(scenario.executor.executed) == 1
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_busy_audio_requires_local_quiet_before_asr_forwarding() -> None:
    scenario = await start_scenario(move_decision())
    scenario.executor.execution_release = asyncio.Event()
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.executor.execution_started.wait()

    loud_frame = b"\xff\x7f" * 1_920
    silent_frame = b"\x00\x00" * 1_920
    audio = scenario.runtime._deps.audio
    for frame in (loud_frame, loud_frame):
        audio.stream.put(frame)  # type: ignore[attr-defined]
    await eventually(lambda: scenario.runtime._busy_audio_observed)
    assert scenario.asr.sent_audio == []
    assert audio.busy_states[-1] is True  # type: ignore[attr-defined]

    scenario.executor.execution_release.set()
    await eventually(lambda: scenario.runtime._planning_task is None)
    assert audio.busy_states[-1] is False  # type: ignore[attr-defined]
    audio.stream.put(loud_frame)  # type: ignore[attr-defined]
    for _ in range(6):
        audio.stream.put(silent_frame)  # type: ignore[attr-defined]
    await eventually(lambda: not scenario.runtime._busy_audio_observed)
    assert scenario.asr.sent_audio == []

    audio.stream.put(loud_frame)  # type: ignore[attr-defined]
    await eventually(lambda: scenario.asr.sent_audio == [loud_frame])
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_repeated_transaction_cancellation_cannot_cancel_committed_execution() -> (
    None
):
    scenario = await start_scenario(move_decision())
    scenario.executor.execution_release = asyncio.Event()
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.executor.execution_started.wait()
    transaction = scenario.runtime._planning_task
    assert transaction is not None

    transaction.cancel()
    await asyncio.sleep(0)
    transaction.cancel()
    await asyncio.sleep(0)
    assert not transaction.done()
    assert not scenario.executor.execution_cancelled

    scenario.executor.execution_release.set()
    await eventually(lambda: transaction.done())
    assert transaction.cancelled()
    assert not scenario.executor.execution_cancelled
    assert len(scenario.executor.executed) == 1
    await scenario.runtime.shutdown(send_end_stream=False)


@pytest.mark.asyncio
async def test_shutdown_waits_for_started_execution_without_cancelling_it() -> None:
    scenario = await start_scenario(move_decision())
    scenario.executor.execution_release = asyncio.Event()
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.executor.execution_started.wait()

    shutdown = asyncio.create_task(scenario.runtime.shutdown(send_end_stream=False))
    await asyncio.sleep(0)
    assert not shutdown.done()
    assert not scenario.executor.execution_cancelled

    scenario.executor.execution_release.set()
    assert await shutdown == 0
    assert not scenario.executor.execution_cancelled
    assert len(scenario.executor.executed) == 1


@pytest.mark.asyncio
async def test_execution_commit_remains_busy_until_outer_transaction_finishes() -> None:
    scenario = await start_scenario(move_decision())
    scenario.asr.stream.put(SupervisedFinalTranscript(1, "turn-1", "Move E2 to E4"))
    await scenario.executor.returned.wait()

    assert scenario.runtime._execution_committed
    assert scenario.runtime._transaction_busy
    await eventually(lambda: scenario.runtime._planning_task is None)
    assert not scenario.runtime._execution_committed
    await scenario.runtime.shutdown(send_end_stream=False)
