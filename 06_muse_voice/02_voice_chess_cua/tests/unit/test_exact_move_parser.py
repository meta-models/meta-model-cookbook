# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import pytest

from voice_chess_cua.domain.chess import ChessMove, ChessSquare, VoiceCommand
from voice_chess_cua.planning.exact_parser import ExactMoveParser
from voice_chess_cua.planning.schema import PlannerDecision
from voice_chess_cua.planning.supervised_command import _mint_supervised_command_text


def supervised(text: str):
    return _mint_supervised_command_text(
        runtime_generation=1,
        asr_generation=1,
        turn_id="turn-1",
        command_text=text,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "source", "destination"),
    [
        ("Move A1 to B2", "A1", "B2"),
        ("Move H8 to A1.", "H8", "A1"),
        ("move e2 to e4", "E2", "E4"),
        ("MOVE E2 TO E4.", "E2", "E4"),
        ("MoVe a8 To H1", "A8", "H1"),
    ],
)
async def test_exact_parser_accepts_only_exact_ascii_grammar(
    text: str,
    source: str,
    destination: str,
) -> None:
    decision = await ExactMoveParser().plan(supervised(text))

    assert decision == PlannerDecision.for_command(
        VoiceCommand.move(
            ChessMove(ChessSquare.parse(source), ChessSquare.parse(destination))
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
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
    ],
)
async def test_exact_parser_rejects_everything_outside_exact_grammar(
    text: str,
) -> None:
    assert await ExactMoveParser().plan(supervised(text)) == PlannerDecision.reject()


@pytest.mark.asyncio
async def test_exact_parser_requires_supervised_command_capability() -> None:
    with pytest.raises(TypeError, match="supervised command text"):
        await ExactMoveParser().plan("Move A1 to B2")
