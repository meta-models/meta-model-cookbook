# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Exact local parser for Voice Chess commands."""

from __future__ import annotations

import re
from typing import Final

from voice_chess_cua.domain.chess import ChessMove, ChessSquare

_MOVE_PATTERN: Final = re.compile(
    r"Move ([A-H][1-8]) to ([A-H][1-8])\.?",
    re.ASCII | re.IGNORECASE,
)


def parse_exact_move(text: str) -> ChessMove | None:
    if not isinstance(text, str):
        raise TypeError("command text must be a string")
    match = _MOVE_PATTERN.fullmatch(text)
    if match is None:
        return None
    source_text, destination_text = (capture.upper() for capture in match.groups())
    if source_text == destination_text:
        return None
    return ChessMove(
        ChessSquare.parse(source_text),
        ChessSquare.parse(destination_text),
    )
