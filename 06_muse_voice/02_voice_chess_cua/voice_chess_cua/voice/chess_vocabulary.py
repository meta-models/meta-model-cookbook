# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Fixed realtime ASR vocabulary for the Voice Chess experience."""

from __future__ import annotations

from typing import Final

from voice_chess_cua.domain.game_state import PieceKind

_FILE_LETTERS: Final = tuple("ABCDEFGH")
_RANK_DIGITS: Final = tuple(str(rank) for rank in range(1, 9))
_FILE_WORDS: Final = (
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
)
_RANK_WORDS: Final = ("one", "two", "three", "four", "five", "six", "seven", "eight")
_CONTEXT_WORDS: Final = ("move", "from", "to", "file", "rank")
_COMMON_SQUARES: Final = ("E2", "E4", "D2", "D4", "G1", "F3")

# Keep recognition bias compact. File and rank words cover arbitrary squares
# without expanding all 64 coordinates or relying on an undocumented limit.
CHESS_ASR_KEYWORDS: Final = (
    *_FILE_LETTERS,
    *_RANK_DIGITS,
    *_FILE_WORDS,
    *_RANK_WORDS,
    *(piece.value for piece in PieceKind),
    *_CONTEXT_WORDS,
    *_COMMON_SQUARES,
)
