# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Validated chess-domain values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class BoardOrientation(StrEnum):
    WHITE_BOTTOM = "whiteBottom"
    BLACK_BOTTOM = "blackBottom"

    @property
    def display_name(self) -> str:
        if self is BoardOrientation.WHITE_BOTTOM:
            return "White at bottom"
        return "Black at bottom"

    def flipped(self) -> BoardOrientation:
        if self is BoardOrientation.WHITE_BOTTOM:
            return BoardOrientation.BLACK_BOTTOM
        return BoardOrientation.WHITE_BOTTOM


@dataclass(frozen=True, slots=True, order=True)
class ChessSquare:
    """A square whose file is zero-based and whose rank is one-based."""

    file: int
    rank: int

    ALL: ClassVar[tuple[ChessSquare, ...]]

    def __post_init__(self) -> None:
        if isinstance(self.file, bool) or not isinstance(self.file, int):
            raise TypeError("file must be an integer")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int):
            raise TypeError("rank must be an integer")
        if not 0 <= self.file < 8 or not 1 <= self.rank <= 8:
            raise ValueError("a chess square must be within A1-H8")

    @classmethod
    def parse(cls, notation: str) -> ChessSquare:
        if not isinstance(notation, str):
            raise TypeError("notation must be a string")
        normalized = notation.strip().upper()
        if len(normalized) != 2:
            raise ValueError(f"invalid chess square: {notation!r}")
        file_character = normalized[0]
        rank_character = normalized[1]
        if file_character not in "ABCDEFGH" or rank_character not in "12345678":
            raise ValueError(f"invalid chess square: {notation!r}")
        return cls(ord(file_character) - ord("A"), int(rank_character))

    @classmethod
    def try_parse(cls, notation: str) -> ChessSquare | None:
        try:
            return cls.parse(notation)
        except (TypeError, ValueError):
            return None

    @classmethod
    def all(cls) -> tuple[ChessSquare, ...]:
        return cls.ALL

    @property
    def notation(self) -> str:
        return f"{chr(ord('A') + self.file)}{self.rank}"

    def __str__(self) -> str:
        return self.notation


ChessSquare.ALL = tuple(
    ChessSquare(file, rank) for rank in range(1, 9) for file in range(8)
)


@dataclass(frozen=True, slots=True)
class ChessMove:
    source: ChessSquare
    destination: ChessSquare

    def __post_init__(self) -> None:
        if not isinstance(self.source, ChessSquare) or not isinstance(
            self.destination, ChessSquare
        ):
            raise TypeError("source and destination must be ChessSquare values")
        if self.source == self.destination:
            raise ValueError("source and destination must differ")
