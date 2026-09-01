# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Semantic Accessibility landmarks for the exact Apple Chess board."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from voice_chess_cua.domain.chess import ChessMove, ChessSquare
from voice_chess_cua.domain.game_state import ChessGameState, infer_move
from voice_chess_cua.domain.geometry import Point
from voice_chess_cua.macos.chess_state import (
    AppleChessGameTitle,
    AppleChessSnapshot,
    parse_apple_chess_snapshot,
    parse_apple_chess_title,
)


class ChessAccessibilityError(RuntimeError):
    pass


class ChessAccessibilityBackend(Protocol):
    def square_centers(self, process_identifier: int) -> Mapping[str, Point]: ...

    def window_title(self, process_identifier: int) -> str: ...

    def game_snapshot(
        self, process_identifier: int
    ) -> tuple[str, Mapping[str, str]]: ...


_SQUARE_SUFFIX = re.compile(r"(?:^|, )([a-h][1-8])$")
_CORNER_SQUARES = frozenset({"a1", "h1", "a8", "h8"})


class _ApplicationServicesChessAccessibilityBackend:
    def __init__(self) -> None:
        from ._native import load_framework

        self._ax = load_framework("ApplicationServices")

    def square_centers(self, process_identifier: int) -> Mapping[str, Point]:
        window = self._single_window(process_identifier)
        centers: dict[str, Point] = {}
        self._collect_square_centers(window, centers)
        if set(centers) != _CORNER_SQUARES:
            raise ChessAccessibilityError("Apple Chess board landmarks are incomplete.")
        return centers

    def window_title(self, process_identifier: int) -> str:
        window = self._single_window(process_identifier)
        title = self._attribute(window, self._ax.kAXTitleAttribute)
        if not isinstance(title, str) or not title.strip():
            raise ChessAccessibilityError("Apple Chess window title is unavailable.")
        return title

    def game_snapshot(self, process_identifier: int) -> tuple[str, Mapping[str, str]]:
        window = self._single_window(process_identifier)
        title = self._attribute(window, self._ax.kAXTitleAttribute)
        if not isinstance(title, str) or not title.strip():
            raise ChessAccessibilityError("Apple Chess window title is unavailable.")
        labels: dict[str, str] = {}
        squares = frozenset(square.notation.lower() for square in ChessSquare.all())
        self._collect_square_labels(window, squares, labels)
        if set(labels) != squares:
            raise ChessAccessibilityError("Apple Chess square state is incomplete.")
        return title, labels

    def _single_window(self, process_identifier: int) -> object:
        application = self._ax.AXUIElementCreateApplication(process_identifier)
        windows = tuple(
            window
            for window in self._elements(
                self._attribute(application, self._ax.kAXWindowsAttribute)
            )
            if not bool(self._attribute(window, self._ax.kAXMinimizedAttribute))
        )
        if len(windows) != 1:
            raise ChessAccessibilityError(
                "Apple Chess must expose exactly one visible AX window."
            )
        return windows[0]

    def _collect_square_centers(
        self, element: object, centers: dict[str, Point]
    ) -> None:
        role = self._attribute(element, self._ax.kAXRoleAttribute)
        if role == self._ax.kAXButtonRole:
            description = self._attribute(element, self._ax.kAXDescriptionAttribute)
            match = _SQUARE_SUFFIX.search(str(description or "").lower())
            if match is not None and match.group(1) in _CORNER_SQUARES:
                square = match.group(1)
                if square in centers:
                    raise ChessAccessibilityError(
                        "Apple Chess exposed duplicate square landmarks."
                    )
                position = self._point_attribute(element, self._ax.kAXPositionAttribute)
                size = self._size_attribute(element, self._ax.kAXSizeAttribute)
                centers[square] = Point(
                    position.x + size.width / 2.0,
                    position.y + size.height / 2.0,
                )
        children = self._elements(
            self._attribute(element, self._ax.kAXChildrenAttribute)
        )
        for child in children:
            self._collect_square_centers(child, centers)

    def _collect_square_labels(
        self,
        element: object,
        squares: frozenset[str],
        labels: dict[str, str],
    ) -> None:
        role = self._attribute(element, self._ax.kAXRoleAttribute)
        if role == self._ax.kAXButtonRole:
            description = str(
                self._attribute(element, self._ax.kAXDescriptionAttribute) or ""
            ).lower()
            match = _SQUARE_SUFFIX.search(description)
            if match is not None and match.group(1) in squares:
                square = match.group(1)
                if square in labels:
                    raise ChessAccessibilityError(
                        "Apple Chess exposed duplicate square state."
                    )
                labels[square] = description
        if len(labels) == len(squares):
            return
        children = self._elements(
            self._attribute(element, self._ax.kAXChildrenAttribute)
        )
        for child in children:
            self._collect_square_labels(child, squares, labels)

    def _point_attribute(self, element: object, name: str) -> Any:
        value = self._attribute(element, name)
        success, point = self._ax.AXValueGetValue(
            value, self._ax.kAXValueCGPointType, None
        )
        if not success:
            raise ChessAccessibilityError(
                "Apple Chess reported an invalid AX position."
            )
        return point

    def _size_attribute(self, element: object, name: str) -> Any:
        value = self._attribute(element, name)
        success, size = self._ax.AXValueGetValue(
            value, self._ax.kAXValueCGSizeType, None
        )
        if not success:
            raise ChessAccessibilityError("Apple Chess reported an invalid AX size.")
        return size

    @staticmethod
    def _elements(value: object | None) -> tuple[object, ...]:
        if value is None or isinstance(value, (str, bytes)):
            return ()
        try:
            return tuple(value)  # type: ignore[arg-type]
        except TypeError:
            return ()

    def _attribute(self, element: object, name: str) -> object | None:
        result = self._ax.AXUIElementCopyAttributeValue(element, name, None)
        if not isinstance(result, tuple) or len(result) != 2 or int(result[0]) != 0:
            return None
        return cast(object, result[1])


class ChessBoardAccessibilityProbe:
    def __init__(self, backend: ChessAccessibilityBackend | None = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> ChessAccessibilityBackend:
        if self._backend is None:
            self._backend = _ApplicationServicesChessAccessibilityBackend()
        return self._backend

    async def square_centers(self, process_identifier: int) -> Mapping[str, Point]:
        return await asyncio.to_thread(self.backend.square_centers, process_identifier)

    async def window_title(self, process_identifier: int) -> str:
        return await asyncio.to_thread(self.backend.window_title, process_identifier)

    async def game_snapshot(
        self, process_identifier: int
    ) -> tuple[str, Mapping[str, str]]:
        return await asyncio.to_thread(self.backend.game_snapshot, process_identifier)


@dataclass(frozen=True, slots=True)
class _MovePostconditionBaseline:
    title: AppleChessGameTitle
    position: ChessGameState


class ChessMovePostcondition:
    def __init__(
        self,
        probe: ChessBoardAccessibilityProbe | None = None,
        *,
        timeout: float = 1.5,
        poll_interval: float = 0.05,
    ) -> None:
        self._probe = probe or ChessBoardAccessibilityProbe()
        self._timeout = timeout
        self._poll_interval = poll_interval

    async def capture(self, process_identifier: int, move: ChessMove) -> object:
        del move
        title, descriptions = await self._probe.game_snapshot(process_identifier)
        return _MovePostconditionBaseline(
            parse_apple_chess_title(title),
            parse_apple_chess_snapshot(AppleChessSnapshot(title, descriptions)),
        )

    async def wait_until_applied(
        self,
        process_identifier: int,
        move: ChessMove,
        before: object,
    ) -> bool:
        if not isinstance(before, _MovePostconditionBaseline):
            return False
        deadline = asyncio.get_running_loop().time() + self._timeout
        while True:
            after = await self.capture(process_identifier, move)
            assert isinstance(after, _MovePostconditionBaseline)
            same_game = (
                after.title.game_number == before.title.game_number
                and after.title.white_player == before.title.white_player
                and after.title.black_player == before.title.black_player
            )
            inferred = (
                infer_move(before.position, after.position) if same_game else None
            )
            if inferred is not None and inferred.is_available and inferred.move == move:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self._poll_interval)
