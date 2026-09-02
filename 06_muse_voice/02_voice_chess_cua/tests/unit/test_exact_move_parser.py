# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import pytest

from voice_chess_cua.command import parse_exact_move
from voice_chess_cua.domain.chess import ChessMove, ChessSquare

REJECTED_COMMANDS = [
    " Move A1 to B2",
    "Move A1 to B2 ",
    "Move  A1 to B2",
    "Move A1  to B2",
    "Move A1 to  B2",
    "Move\tA1 to B2",
    "Move A1\tto B2",
    "Move A1 to\tB2",
    "Move A1 to B2\n",
    "Move A1 to B2!",
    "Move A1 to B2..",
    "Please Move A1 to B2",
    "Move A1 to B2 please",
    "Move A one to B two",
    "Move I1 to B2",
    "Move A0 to B2",
    "Move A1 to B9",
    "Move A1 B2",
    "Move A1 from B2",
    "Move A1 to A1",
    "move a1 to A1.",
    "M\u0130ve A1 to B2",
    "Move \u212a1 to B2",
]


def test_exact_move_returns_normalized_move() -> None:
    assert parse_exact_move("Move e2 to E4.") == ChessMove(
        ChessSquare.parse("E2"),
        ChessSquare.parse("E4"),
    )


@pytest.mark.parametrize("text", REJECTED_COMMANDS)
def test_non_exact_command_is_rejected(text: str) -> None:
    assert parse_exact_move(text) is None
