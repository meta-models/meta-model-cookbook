# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Process host that keeps AppKit on the main thread and asyncio on a worker."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType
from typing import Any, Protocol, runtime_checkable

from .app import RuntimeExitCode


class HostedRuntime(Protocol):
    async def run_until_stopped(self) -> int: ...

    async def shutdown(self, *, exit_code: int) -> int: ...


@runtime_checkable
class MainThreadWorkerWaiter(Protocol):
    def wait_for_worker(self, worker: threading.Thread, timeout: float) -> None: ...


class AppKitRunLoop(Protocol):
    @property
    def stop_requested(self) -> bool: ...

    def run(self) -> int: ...

    async def stop(self, exit_code: int) -> None: ...


@dataclass(slots=True)
class _WorkerState:
    loop: asyncio.AbstractEventLoop | None = None
    exit_code: int = int(RuntimeExitCode.INTERNAL_ERROR)
    error: BaseException | None = None


class AppKitRuntimeProcess:
    """Run the native event loop on main while the Voice CUA runtime uses asyncio."""

    def __init__(
        self,
        runtime: HostedRuntime,
        application_host: AppKitRunLoop,
        *,
        force_exit: Callable[[int], object] = os._exit,
        worker_join_timeout: float = 10.0,
    ) -> None:
        if worker_join_timeout <= 0:
            raise ValueError("worker_join_timeout must be positive")
        self._runtime = runtime
        self._application_host = application_host
        self._force_exit = force_exit
        self._worker_join_timeout = worker_join_timeout

    def run(self) -> int:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("The AppKit process host must run on the main thread.")

        state = _WorkerState()
        ready = threading.Event()
        worker = threading.Thread(
            target=self._run_worker,
            args=(state, ready),
            name="voice-cua-asyncio",
            daemon=False,
        )
        previous_handlers: dict[signal.Signals, Any] = {}
        signal_count = 0

        def handle_signal(signal_number: int, _frame: FrameType | None) -> None:
            nonlocal signal_count
            signal_count += 1
            exit_code = 128 + signal_number
            if signal_count > 1:
                self._force_exit(exit_code)
                return
            loop = state.loop
            if loop is None or loop.is_closed():
                self._force_exit(exit_code)
                return
            asyncio.run_coroutine_threadsafe(
                self._runtime.shutdown(exit_code=exit_code),
                loop,
            )

        for signal_number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, handle_signal)

        worker.start()
        ready.wait()
        try:
            self._application_host.run()
        finally:
            if worker.is_alive() and not self._application_host.stop_requested:
                loop = state.loop
                if loop is not None and not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._runtime.shutdown(
                            exit_code=RuntimeExitCode.INTERNAL_ERROR
                        ),
                        loop,
                    )
            if isinstance(self._application_host, MainThreadWorkerWaiter):
                self._application_host.wait_for_worker(
                    worker, self._worker_join_timeout
                )
            else:
                worker.join(self._worker_join_timeout)
            for signal_number, handler in previous_handlers.items():
                signal.signal(signal_number, handler)
            if worker.is_alive():
                self._force_exit(int(RuntimeExitCode.INTERNAL_ERROR))
                raise RuntimeError("The Voice CUA asyncio worker did not stop.")

        if state.error is not None:
            raise RuntimeError("The Voice CUA asyncio worker failed.") from state.error
        return state.exit_code

    def _run_worker(self, state: _WorkerState, ready: threading.Event) -> None:
        async def run_runtime() -> int:
            state.loop = asyncio.get_running_loop()
            ready.set()
            try:
                return await self._runtime.run_until_stopped()
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit) as error:
                state.error = error
                await self._application_host.stop(int(RuntimeExitCode.INTERNAL_ERROR))
                return int(RuntimeExitCode.INTERNAL_ERROR)
            except Exception as error:  # noqa: BLE001 - process boundary stops AppKit.
                state.error = error
                await self._application_host.stop(int(RuntimeExitCode.INTERNAL_ERROR))
                return int(RuntimeExitCode.INTERNAL_ERROR)

        try:
            state.exit_code = asyncio.run(run_runtime())
        finally:
            ready.set()
