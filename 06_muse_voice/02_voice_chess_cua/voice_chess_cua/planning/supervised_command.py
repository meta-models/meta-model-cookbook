# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Opaque supervised command capability accepted by the command planner."""

from __future__ import annotations

from dataclasses import dataclass


class _SupervisedCommandSeal:
    __slots__ = ()


_SUPERVISED_COMMAND_SEAL = _SupervisedCommandSeal()


@dataclass(frozen=True, slots=True, init=False)
class SupervisedCommandText:
    """One command bound to a supervised ASR turn and runtime generation."""

    runtime_generation: int
    asr_generation: int
    turn_id: str
    value: str
    _seal: _SupervisedCommandSeal

    def __init__(
        self,
        *,
        runtime_generation: int,
        asr_generation: int,
        turn_id: str,
        command_text: str,
        _seal: _SupervisedCommandSeal,
    ) -> None:
        if _seal is not _SUPERVISED_COMMAND_SEAL:
            raise TypeError(
                "SupervisedCommandText may only be minted by the supervised runtime"
            )
        for name, value in (
            ("runtime_generation", runtime_generation),
            ("asr_generation", asr_generation),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        normalized_turn = turn_id.strip()
        if not isinstance(command_text, str):
            raise TypeError("command_text must be a string")
        if not normalized_turn or not command_text.strip():
            raise ValueError("supervised command text requires a turn and command text")
        object.__setattr__(self, "runtime_generation", runtime_generation)
        object.__setattr__(self, "asr_generation", asr_generation)
        object.__setattr__(self, "turn_id", normalized_turn)
        object.__setattr__(self, "value", command_text)
        object.__setattr__(self, "_seal", _seal)


def _mint_supervised_command_text(
    *,
    runtime_generation: int,
    asr_generation: int,
    turn_id: str,
    command_text: str,
) -> SupervisedCommandText:
    return SupervisedCommandText(
        runtime_generation=runtime_generation,
        asr_generation=asr_generation,
        turn_id=turn_id,
        command_text=command_text,
        _seal=_SUPERVISED_COMMAND_SEAL,
    )
