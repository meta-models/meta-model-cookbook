# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from voice_chess_cua.domain.chess import VoiceCommand


class PlannerDecisionKind(StrEnum):
    COMMAND = "command"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    kind: PlannerDecisionKind
    command: VoiceCommand | None = None

    def __post_init__(self) -> None:
        if self.kind is PlannerDecisionKind.COMMAND:
            if not isinstance(self.command, VoiceCommand):
                raise ValueError("command decisions require a VoiceCommand")
        elif self.command is not None:
            raise ValueError("reject decisions cannot contain a command")

    @classmethod
    def for_command(cls, command: VoiceCommand) -> PlannerDecision:
        return cls(PlannerDecisionKind.COMMAND, command)

    @classmethod
    def reject(cls) -> PlannerDecision:
        return cls(PlannerDecisionKind.REJECT)
