# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Exact local parser for supervised Voice Chess commands."""

from __future__ import annotations

import re
from typing import Final

from voice_chess_cua.domain.chess import ChessMove, ChessSquare, VoiceCommand

from .schema import PlannerDecision
from .supervised_command import SupervisedCommandText

_MOVE_PATTERN: Final = re.compile(
    r"Move ([A-H][1-8]) to ([A-H][1-8])\.?",
    re.ASCII | re.IGNORECASE,
)


class ExactMoveParser:
    """Parse only the public recipe's exact move grammar."""

    async def plan(self, supervised_command: object) -> PlannerDecision:
        if not isinstance(supervised_command, SupervisedCommandText):
            raise TypeError("The parser requires supervised command text.")

        match = _MOVE_PATTERN.fullmatch(supervised_command.value)
        if match is None:
            return PlannerDecision.reject()

        source_text, destination_text = (capture.upper() for capture in match.groups())
        if source_text == destination_text:
            return PlannerDecision.reject()

        move = ChessMove(
            source=ChessSquare.parse(source_text),
            destination=ChessSquare.parse(destination_text),
        )
        return PlannerDecision.for_command(VoiceCommand.move(move))
