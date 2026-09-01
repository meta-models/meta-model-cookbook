# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Apple Chess Accessibility snapshot parsing and polling."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from voice_chess_cua.domain.chess import ChessMove, ChessSquare
from voice_chess_cua.domain.game_state import (
    ChessGameState,
    ChessPiece,
    MoveInference,
    PieceColor,
    PieceKind,
    infer_move,
)


class ChessStateParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AppleChessGameTitle:
    game_number: int
    white_player: str
    black_player: str
    side_to_move: PieceColor | None
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class AppleChessSquareState:
    square: ChessSquare
    piece: ChessPiece | None


@dataclass(frozen=True, slots=True)
class AppleChessSnapshot:
    title: str
    square_descriptions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ChessStateObservation:
    position: ChessGameState
    inferred_move: MoveInference | None
    title: AppleChessGameTitle


class AsyncChessSnapshotProbe(Protocol):
    async def snapshot(self, process_identifier: int) -> AppleChessSnapshot: ...


class ChessGameSnapshotProbe(Protocol):
    async def game_snapshot(
        self, process_identifier: int
    ) -> tuple[str, Mapping[str, str]]: ...


_TITLE_PATTERN = re.compile(
    r"^Game\s+(?P<number>[1-9][0-9]*)\s*\|\s*"
    r"(?P<white>.+?)\s+-\s+(?P<black>.+?)\s+"
    r"\((?P<status>White\s+to\s+Move|Black\s+to\s+Move|"
    r"White\s+wins!?|Black\s+wins!?|Draw!?|Stalemate!?)\)$",
    re.IGNORECASE,
)
_SQUARE_PATTERN = re.compile(
    r"^(?:(?P<color>white|black)\s+"
    r"(?P<piece>king|queen|rook|bishop|knight|pawn),\s*)?"
    r"(?P<square>[a-h][1-8])$",
    re.IGNORECASE,
)


def parse_apple_chess_title(title: str) -> AppleChessGameTitle:
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    match = _TITLE_PATTERN.fullmatch(" ".join(title.strip().split()))
    if match is None:
        raise ChessStateParseError("unsupported Apple Chess game title")
    white_player = match.group("white").strip()
    black_player = match.group("black").strip()
    if not white_player or not black_player:
        raise ChessStateParseError("Apple Chess game title contains an empty player")
    status = " ".join(match.group("status").split())
    turn_match = re.fullmatch(r"(White|Black) to Move", status, re.IGNORECASE)
    side_to_move = (
        None if turn_match is None else PieceColor(turn_match.group(1).lower())
    )
    outcome = None if turn_match is not None else status.rstrip("!")
    return AppleChessGameTitle(
        game_number=int(match.group("number")),
        white_player=white_player,
        black_player=black_player,
        side_to_move=side_to_move,
        outcome=outcome,
    )


def parse_apple_chess_square(description: str) -> AppleChessSquareState:
    if not isinstance(description, str):
        raise TypeError("description must be a string")
    match = _SQUARE_PATTERN.fullmatch(" ".join(description.strip().split()))
    if match is None:
        raise ChessStateParseError(
            f"unsupported Apple Chess square description: {description!r}"
        )
    square = ChessSquare.parse(match.group("square"))
    color = match.group("color")
    piece = match.group("piece")
    if color is None or piece is None:
        return AppleChessSquareState(square, None)
    return AppleChessSquareState(
        square,
        ChessPiece(PieceColor(color.lower()), PieceKind(piece.lower())),
    )


def parse_apple_chess_snapshot(snapshot: AppleChessSnapshot) -> ChessGameState:
    if not isinstance(snapshot, AppleChessSnapshot):
        raise TypeError("snapshot must be an AppleChessSnapshot")
    title = parse_apple_chess_title(snapshot.title)
    parsed: dict[ChessSquare, ChessPiece | None] = {}
    for raw_square, description in snapshot.square_descriptions.items():
        square = ChessSquare.try_parse(raw_square)
        if square is None:
            raise ChessStateParseError(
                f"invalid Apple Chess snapshot key: {raw_square!r}"
            )
        if square in parsed:
            raise ChessStateParseError(
                f"duplicate Apple Chess snapshot square: {square}"
            )
        square_state = parse_apple_chess_square(description)
        if square_state.square != square:
            raise ChessStateParseError(
                f"Apple Chess snapshot key {square} does not match "
                f"description square {square_state.square}"
            )
        parsed[square] = square_state.piece
    try:
        return ChessGameState(parsed, title.side_to_move)
    except (TypeError, ValueError) as error:
        raise ChessStateParseError(str(error)) from error


class ChessAccessibilitySnapshotProbe:
    """Compose existing async AX label and title probes into raw snapshots."""

    def __init__(self, probe: ChessGameSnapshotProbe) -> None:
        self._probe = probe

    async def snapshot(self, process_identifier: int) -> AppleChessSnapshot:
        title, descriptions = await self._probe.game_snapshot(process_identifier)
        return AppleChessSnapshot(title, descriptions)


class ChessStateObserver:
    """Poll an injected snapshot source and infer each complete board transition."""

    def __init__(
        self,
        probe: AsyncChessSnapshotProbe,
        *,
        poll_interval: float = 0.1,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self._probe = probe
        self._poll_interval = poll_interval
        self._sleep = sleep
        self._previous: ChessGameState | None = None
        self._previous_title: AppleChessGameTitle | None = None
        self._candidate: AppleChessSnapshot | None = None
        self._confirmed_hint: ChessMove | None = None

    @property
    def previous(self) -> ChessGameState | None:
        return self._previous

    def reset(self) -> None:
        self._previous = None
        self._previous_title = None
        self._candidate = None
        self._confirmed_hint = None

    def confirm_local_move(self, move: ChessMove) -> None:
        if not isinstance(move, ChessMove):
            raise TypeError("confirmed move hint must be a ChessMove")
        self._confirmed_hint = move

    async def poll(self, process_identifier: int) -> ChessStateObservation | None:
        snapshot = await self._probe.snapshot(process_identifier)
        if self._candidate != snapshot:
            self._candidate = snapshot
            return None
        title = parse_apple_chess_title(snapshot.title)
        position = parse_apple_chess_snapshot(snapshot)
        previous = self._previous
        previous_title = self._previous_title
        if previous == position and previous_title == title:
            return None
        new_game = (
            previous_title is not None
            and previous_title.game_number != title.game_number
        )
        inferred = (
            None if previous is None or new_game else infer_move(previous, position)
        )
        hint = self._confirmed_hint
        if (
            previous is not None
            and inferred is not None
            and not inferred.is_available
            and hint is not None
        ):
            reconciled = _reconcile_confirmed_move(previous, position, hint)
            if reconciled is not None:
                inferred = reconciled
        self._confirmed_hint = None
        self._previous = position
        self._previous_title = title
        return ChessStateObservation(position, inferred, title)

    async def observations(
        self, process_identifier: int
    ) -> AsyncIterator[ChessStateObservation]:
        while True:
            observation = await self.poll(process_identifier)
            if observation is not None:
                yield observation
            await self._sleep(self._poll_interval)


def _reconcile_confirmed_move(
    before: ChessGameState,
    after: ChessGameState,
    hint: ChessMove,
) -> MoveInference | None:
    mover = before.piece_at(hint.source)
    if mover is None:
        return None
    pieces = {square: before.piece_at(square) for square in ChessSquare.all()}
    destination_before = pieces[hint.destination]
    pieces[hint.source] = None
    pieces[hint.destination] = mover

    file_delta = hint.destination.file - hint.source.file
    rank_delta = hint.destination.rank - hint.source.rank
    if mover.kind is PieceKind.KING and rank_delta == 0 and abs(file_delta) == 2:
        rank = hint.source.rank
        if file_delta > 0:
            rook_source, rook_destination = ChessSquare(7, rank), ChessSquare(5, rank)
        else:
            rook_source, rook_destination = ChessSquare(0, rank), ChessSquare(3, rank)
        rook = pieces[rook_source]
        if rook != ChessPiece(mover.color, PieceKind.ROOK):
            return None
        pieces[rook_source] = None
        pieces[rook_destination] = rook
    elif (
        mover.kind is PieceKind.PAWN
        and abs(file_delta) == 1
        and destination_before is None
    ):
        captured_square = ChessSquare(hint.destination.file, hint.source.rank)
        captured = pieces[captured_square]
        if captured != ChessPiece(mover.color.opposite(), PieceKind.PAWN):
            return None
        pieces[captured_square] = None

    intermediate = ChessGameState(
        pieces,
        None if before.side_to_move is None else before.side_to_move.opposite(),
    )
    confirmed = infer_move(before, intermediate)
    if not confirmed.is_available:
        return None
    if intermediate.pieces == after.pieces:
        return confirmed
    reply = infer_move(intermediate, after)
    return reply if reply.is_available else None


parse_game_title = parse_apple_chess_title
parse_square_description = parse_apple_chess_square
parse_chess_position = parse_apple_chess_snapshot
ChessSnapshotProbe = AsyncChessSnapshotProbe
