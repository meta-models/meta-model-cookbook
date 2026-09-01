# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Awaitable dispatch of AppKit work to the process main thread."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial

from ._asyncio import call_soon_threadsafe_if_open
from ._native import load_framework


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
