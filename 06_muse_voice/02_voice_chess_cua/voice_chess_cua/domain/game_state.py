# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Immutable Chess positions and conservative move inference."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from voice_chess_cua.domain.chess import ChessMove, ChessSquare


class PieceColor(StrEnum):
    WHITE = "white"
    BLACK = "black"

    def opposite(self) -> PieceColor:
        if self is PieceColor.WHITE:
            return PieceColor.BLACK
        return PieceColor.WHITE


class PieceKind(StrEnum):
    KING = "king"
    QUEEN = "queen"
    ROOK = "rook"
    BISHOP = "bishop"
    KNIGHT = "knight"
    PAWN = "pawn"


@dataclass(frozen=True, slots=True)
class ChessPiece:
    color: PieceColor
    kind: PieceKind

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", PieceColor(self.color))
        object.__setattr__(self, "kind", PieceKind(self.kind))


@dataclass(frozen=True, slots=True, init=False)
class ChessGameState:
    """A complete board snapshot in rank-major A1-H8 order."""

    pieces: tuple[ChessPiece | None, ...]
    side_to_move: PieceColor | None

    def __init__(
        self,
        pieces: Mapping[ChessSquare, ChessPiece | None]
        | Iterable[tuple[ChessSquare, ChessPiece | None]],
        side_to_move: PieceColor | None = None,
    ) -> None:
        entries = (
            tuple(pieces.items()) if isinstance(pieces, Mapping) else tuple(pieces)
        )
        board: dict[ChessSquare, ChessPiece | None] = {}
        for square, piece in entries:
            if not isinstance(square, ChessSquare):
                raise TypeError("position keys must be ChessSquare values")
            if square in board:
                raise ValueError(f"duplicate square in position: {square}")
            if piece is not None and not isinstance(piece, ChessPiece):
                raise TypeError("position values must be ChessPiece values or None")
            board[square] = piece
        expected = frozenset(ChessSquare.all())
        actual = frozenset(board)
        if actual != expected:
            missing = len(expected - actual)
            extra = len(actual - expected)
            raise ValueError(
                f"a complete Chess position requires all 64 squares "
                f"(missing={missing}, extra={extra})"
            )
        normalized_side = None if side_to_move is None else PieceColor(side_to_move)
        object.__setattr__(
            self, "pieces", tuple(board[square] for square in ChessSquare.all())
        )
        object.__setattr__(self, "side_to_move", normalized_side)

    @classmethod
    def empty(cls, side_to_move: PieceColor | None = None) -> ChessGameState:
        return cls({square: None for square in ChessSquare.all()}, side_to_move)

    def piece_at(self, square: ChessSquare) -> ChessPiece | None:
        if not isinstance(square, ChessSquare):
            raise TypeError("square must be a ChessSquare")
        return self.pieces[_square_index(square)]

    def occupied(self) -> tuple[tuple[ChessSquare, ChessPiece], ...]:
        return tuple(
            (square, piece)
            for square, piece in zip(ChessSquare.all(), self.pieces, strict=True)
            if piece is not None
        )

    def changed_squares(self, other: ChessGameState) -> tuple[ChessSquare, ...]:
        if not isinstance(other, ChessGameState):
            raise TypeError("other must be a ChessGameState")
        return tuple(
            square
            for square in ChessSquare.all()
            if self.piece_at(square) != other.piece_at(square)
        )


class MoveKind(StrEnum):
    NORMAL = "normal"
    CAPTURE = "capture"
    CASTLING = "castling"
    EN_PASSANT = "en-passant"
    PROMOTION = "promotion"
    UNAVAILABLE = "unavailable"


class MoveUnavailableReason(StrEnum):
    UNCHANGED = "unchanged"
    TURN_MISMATCH = "turn-mismatch"
    UNSUPPORTED_TRANSITION = "unsupported-transition"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class MoveInference:
    kind: MoveKind
    move: ChessMove | None = None
    moved_piece: ChessPiece | None = None
    captured_piece: ChessPiece | None = None
    captured_square: ChessSquare | None = None
    promotion: PieceKind | None = None
    rook_move: ChessMove | None = None
    unavailable_reason: MoveUnavailableReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", MoveKind(self.kind))
        if self.promotion is not None:
            object.__setattr__(self, "promotion", PieceKind(self.promotion))
        if self.unavailable_reason is not None:
            object.__setattr__(
                self,
                "unavailable_reason",
                MoveUnavailableReason(self.unavailable_reason),
            )
        if self.kind is MoveKind.UNAVAILABLE:
            if self.move is not None or self.moved_piece is not None:
                raise ValueError("unavailable inference cannot contain a move")
            if self.unavailable_reason is None:
                raise ValueError("unavailable inference requires a reason")
            return
        if self.move is None or self.moved_piece is None:
            raise ValueError("available inference requires a move and moved piece")
        if self.unavailable_reason is not None:
            raise ValueError("available inference cannot contain an unavailable reason")
        if self.kind is MoveKind.PROMOTION and self.promotion is None:
            raise ValueError("promotion inference requires the promoted piece kind")
        if self.kind is MoveKind.CASTLING and self.rook_move is None:
            raise ValueError("castling inference requires the rook move")

    @property
    def is_available(self) -> bool:
        return self.kind is not MoveKind.UNAVAILABLE

    @classmethod
    def unavailable(cls, reason: MoveUnavailableReason) -> MoveInference:
        return cls(MoveKind.UNAVAILABLE, unavailable_reason=reason)


_PROMOTION_KINDS = frozenset(
    {PieceKind.QUEEN, PieceKind.ROOK, PieceKind.BISHOP, PieceKind.KNIGHT}
)


def infer_move(before: ChessGameState, after: ChessGameState) -> MoveInference:
    """Infer one pseudo-legal move only when the complete transition is unique."""

    if not isinstance(before, ChessGameState) or not isinstance(after, ChessGameState):
        raise TypeError("before and after must be ChessGameState values")
    changed = frozenset(before.changed_squares(after))
    if not changed:
        return MoveInference.unavailable(MoveUnavailableReason.UNCHANGED)
    if not _turns_are_compatible(before, after):
        return MoveInference.unavailable(MoveUnavailableReason.TURN_MISMATCH)

    candidates = _ordinary_candidates(before, after, changed)
    candidates.extend(_en_passant_candidates(before, after, changed))
    candidates.extend(_castling_candidates(before, after, changed))
    unique = tuple(dict.fromkeys(candidates))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1 or _has_ambiguous_arrival(before, after, changed):
        return MoveInference.unavailable(MoveUnavailableReason.AMBIGUOUS)
    return MoveInference.unavailable(MoveUnavailableReason.UNSUPPORTED_TRANSITION)


def _ordinary_candidates(
    before: ChessGameState,
    after: ChessGameState,
    changed: frozenset[ChessSquare],
) -> list[MoveInference]:
    if len(changed) != 2:
        return []
    sources = tuple(
        square
        for square in changed
        if before.piece_at(square) is not None and after.piece_at(square) is None
    )
    destinations = tuple(
        square for square in changed if after.piece_at(square) is not None
    )
    candidates: list[MoveInference] = []
    for source in sources:
        mover = before.piece_at(source)
        assert mover is not None
        if not _mover_matches_known_turns(before, after, mover.color):
            continue
        for destination in destinations:
            arrived = after.piece_at(destination)
            captured = before.piece_at(destination)
            if arrived is None or arrived.color is not mover.color:
                continue
            move = ChessMove(source, destination)
            if arrived == mover and _is_pseudo_legal_move(
                before, mover, move, captured
            ):
                kind = MoveKind.NORMAL if captured is None else MoveKind.CAPTURE
                candidates.append(
                    MoveInference(
                        kind,
                        move,
                        mover,
                        captured_piece=captured,
                        captured_square=destination if captured is not None else None,
                    )
                )
                continue
            if (
                mover.kind is PieceKind.PAWN
                and arrived.kind in _PROMOTION_KINDS
                and _is_promotion_move(mover, move, captured)
            ):
                candidates.append(
                    MoveInference(
                        MoveKind.PROMOTION,
                        move,
                        mover,
                        captured_piece=captured,
                        captured_square=destination if captured is not None else None,
                        promotion=arrived.kind,
                    )
                )
    return candidates


def _en_passant_candidates(
    before: ChessGameState,
    after: ChessGameState,
    changed: frozenset[ChessSquare],
) -> list[MoveInference]:
    if len(changed) != 3:
        return []
    candidates: list[MoveInference] = []
    for source in changed:
        mover = before.piece_at(source)
        if (
            mover is None
            or mover.kind is not PieceKind.PAWN
            or after.piece_at(source) is not None
        ):
            continue
        if not _mover_matches_known_turns(before, after, mover.color):
            continue
        required_source_rank = 5 if mover.color is PieceColor.WHITE else 4
        if source.rank != required_source_rank:
            continue
        direction = 1 if mover.color is PieceColor.WHITE else -1
        for destination in changed:
            if destination == source or before.piece_at(destination) is not None:
                continue
            if after.piece_at(destination) != mover:
                continue
            if destination.rank - source.rank != direction:
                continue
            if abs(destination.file - source.file) != 1:
                continue
            captured_square = ChessSquare(destination.file, source.rank)
            captured = before.piece_at(captured_square)
            if (
                captured_square not in changed
                or captured != ChessPiece(mover.color.opposite(), PieceKind.PAWN)
                or after.piece_at(captured_square) is not None
            ):
                continue
            candidates.append(
                MoveInference(
                    MoveKind.EN_PASSANT,
                    ChessMove(source, destination),
                    mover,
                    captured_piece=captured,
                    captured_square=captured_square,
                )
            )
    return candidates


def _castling_candidates(
    before: ChessGameState,
    after: ChessGameState,
    changed: frozenset[ChessSquare],
) -> list[MoveInference]:
    if len(changed) != 4:
        return []
    candidates: list[MoveInference] = []
    for color, rank in ((PieceColor.WHITE, 1), (PieceColor.BLACK, 8)):
        if not _mover_matches_known_turns(before, after, color):
            continue
        for king_destination_file, rook_source_file, rook_destination_file in (
            (6, 7, 5),
            (2, 0, 3),
        ):
            king_source = ChessSquare(4, rank)
            king_destination = ChessSquare(king_destination_file, rank)
            rook_source = ChessSquare(rook_source_file, rank)
            rook_destination = ChessSquare(rook_destination_file, rank)
            expected_changed = frozenset(
                {king_source, king_destination, rook_source, rook_destination}
            )
            if changed != expected_changed:
                continue
            king = ChessPiece(color, PieceKind.KING)
            rook = ChessPiece(color, PieceKind.ROOK)
            if (
                before.piece_at(king_source) != king
                or before.piece_at(rook_source) != rook
                or before.piece_at(king_destination) is not None
                or before.piece_at(rook_destination) is not None
                or after.piece_at(king_source) is not None
                or after.piece_at(rook_source) is not None
                or after.piece_at(king_destination) != king
                or after.piece_at(rook_destination) != rook
            ):
                continue
            between_files = range(5, 7) if rook_source_file == 7 else range(1, 4)
            if any(
                before.piece_at(ChessSquare(file, rank)) is not None
                for file in between_files
            ):
                continue
            candidates.append(
                MoveInference(
                    MoveKind.CASTLING,
                    ChessMove(king_source, king_destination),
                    king,
                    rook_move=ChessMove(rook_source, rook_destination),
                )
            )
    return candidates


def _turns_are_compatible(before: ChessGameState, after: ChessGameState) -> bool:
    if before.side_to_move is None or after.side_to_move is None:
        return True
    return after.side_to_move is before.side_to_move.opposite()


def _mover_matches_known_turns(
    before: ChessGameState,
    after: ChessGameState,
    mover: PieceColor,
) -> bool:
    if before.side_to_move is not None and before.side_to_move is not mover:
        return False
    return after.side_to_move is None or after.side_to_move is mover.opposite()


def _has_ambiguous_arrival(
    before: ChessGameState,
    after: ChessGameState,
    changed: frozenset[ChessSquare],
) -> bool:
    """Detect incomplete deltas with more than one plausible source for one arrival."""

    for destination in changed:
        arrived = after.piece_at(destination)
        if arrived is None:
            continue
        sources = 0
        captured = before.piece_at(destination)
        for source in changed:
            if source == destination or after.piece_at(source) is not None:
                continue
            mover = before.piece_at(source)
            if mover != arrived:
                continue
            if not _mover_matches_known_turns(before, after, mover.color):
                continue
            if _is_pseudo_legal_move(
                before, mover, ChessMove(source, destination), captured
            ):
                sources += 1
        if sources > 1:
            return True
    return False


def _is_pseudo_legal_move(
    position: ChessGameState,
    piece: ChessPiece,
    move: ChessMove,
    captured: ChessPiece | None,
) -> bool:
    if captured is not None and captured.color is piece.color:
        return False
    file_delta = move.destination.file - move.source.file
    rank_delta = move.destination.rank - move.source.rank
    absolute_file = abs(file_delta)
    absolute_rank = abs(rank_delta)
    if piece.kind is PieceKind.KNIGHT:
        return (absolute_file, absolute_rank) in {(1, 2), (2, 1)}
    if piece.kind is PieceKind.KING:
        return max(absolute_file, absolute_rank) == 1
    if piece.kind is PieceKind.PAWN:
        direction = 1 if piece.color is PieceColor.WHITE else -1
        promotion_rank = 8 if piece.color is PieceColor.WHITE else 1
        if move.destination.rank == promotion_rank:
            return False
        if captured is not None:
            return absolute_file == 1 and rank_delta == direction
        if file_delta != 0:
            return False
        if rank_delta == direction:
            return True
        starting_rank = 2 if piece.color is PieceColor.WHITE else 7
        if move.source.rank != starting_rank or rank_delta != 2 * direction:
            return False
        intermediate = ChessSquare(move.source.file, move.source.rank + direction)
        return position.piece_at(intermediate) is None
    if piece.kind is PieceKind.ROOK:
        return (file_delta == 0 or rank_delta == 0) and _path_is_clear(position, move)
    if piece.kind is PieceKind.BISHOP:
        return absolute_file == absolute_rank and _path_is_clear(position, move)
    return (
        file_delta == 0 or rank_delta == 0 or absolute_file == absolute_rank
    ) and _path_is_clear(position, move)


def _is_promotion_move(
    pawn: ChessPiece,
    move: ChessMove,
    captured: ChessPiece | None,
) -> bool:
    direction = 1 if pawn.color is PieceColor.WHITE else -1
    source_rank = 7 if pawn.color is PieceColor.WHITE else 2
    destination_rank = 8 if pawn.color is PieceColor.WHITE else 1
    if move.source.rank != source_rank or move.destination.rank != destination_rank:
        return False
    if move.destination.rank - move.source.rank != direction:
        return False
    file_delta = abs(move.destination.file - move.source.file)
    if captured is None:
        return file_delta == 0
    return captured.color is not pawn.color and file_delta == 1


def _path_is_clear(position: ChessGameState, move: ChessMove) -> bool:
    file_step = _sign(move.destination.file - move.source.file)
    rank_step = _sign(move.destination.rank - move.source.rank)
    file = move.source.file + file_step
    rank = move.source.rank + rank_step
    while (file, rank) != (move.destination.file, move.destination.rank):
        if position.piece_at(ChessSquare(file, rank)) is not None:
            return False
        file += file_step
        rank += rank_step
    return True


def _square_index(square: ChessSquare) -> int:
    return (square.rank - 1) * 8 + square.file


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)
