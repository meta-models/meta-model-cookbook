# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Shared native helper functions for macOS adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from importlib import import_module
from types import ModuleType


class NativeDependencyError(RuntimeError):
    """Raised when a concrete macOS adapter cannot load its native bridge."""


def call_soon_threadsafe_if_open(
    loop: asyncio.AbstractEventLoop,
    callback: Callable[[], None],
) -> bool:
    """Schedule callback unless the owning event loop has already closed."""
    if loop.is_closed():
        return False
    try:
        loop.call_soon_threadsafe(callback)
    except RuntimeError:
        # The loop can close between is_closed() and call_soon_threadsafe().
        return False
    return True


async def run_on_main[T](work: Callable[[], T]) -> T:
    foundation = load_framework("Foundation")
    if bool(foundation.NSThread.isMainThread()):
        return work()

    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def settle_result(result: T) -> None:
        if not future.done():
            future.set_result(result)

    def settle_error(error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)

    def execute() -> None:
        if future.cancelled():
            return
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - propagate Objective-C failures.
            call_soon_threadsafe_if_open(loop, partial(settle_error, error))
        else:
            call_soon_threadsafe_if_open(loop, partial(settle_result, result))

    foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(execute)
    return await future


def load_framework(module_name: str) -> ModuleType:
    try:
        return import_module(module_name)
    except ImportError as error:
        raise NativeDependencyError(
            f"The {module_name} PyObjC framework is required for this macOS operation."
        ) from error
