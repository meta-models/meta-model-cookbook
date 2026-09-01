# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Exception-safe dispatch from native completion callbacks to asyncio."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


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
