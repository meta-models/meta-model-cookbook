# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Main-thread NSApplication host for the Python runtime."""

from __future__ import annotations

import threading
import time
from typing import Any

from ._main_thread import run_on_main
from ._native import load_framework


class AppKitHost:
    def __init__(self, application: object | None = None) -> None:
        self._application = application
        self._foundation: Any | None = None
        self._exit_code = 0
        self._running = False
        self._stop_requested = False
        self._state_lock = threading.Lock()

    @property
    def application(self) -> object:
        if self._application is None:
            from ._native import load_framework

            appkit = load_framework("AppKit")
            self._foundation = load_framework("Foundation")
            application = appkit.NSApplication.sharedApplication()
            application.setActivationPolicy_(
                appkit.NSApplicationActivationPolicyAccessory
            )
            self._application = application
        return self._application

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def stop_requested(self) -> bool:
        with self._state_lock:
            return self._stop_requested

    def run(self) -> int:
        application = self.application
        with self._state_lock:
            if self._stop_requested:
                return self._exit_code
            self._running = True
        try:
            application.run()  # type: ignore[attr-defined]
        finally:
            with self._state_lock:
                self._running = False
        return self._exit_code

    def wait_for_worker(self, worker: threading.Thread, timeout: float) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("AppKit worker waiting must run on the main thread")
        deadline = time.monotonic() + timeout
        foundation = load_framework("Foundation")
        run_loop = foundation.NSRunLoop.currentRunLoop()
        while worker.is_alive() and time.monotonic() < deadline:
            until = foundation.NSDate.dateWithTimeIntervalSinceNow_(0.01)
            run_loop.runUntilDate_(until)
        worker.join(timeout=0)

    async def stop(self, exit_code: int) -> None:
        with self._state_lock:
            self._exit_code = int(exit_code)
            self._stop_requested = True
            running = self._running
        if not running:
            return

        def stop_run_loop() -> None:
            appkit = load_framework("AppKit")
            application = self.application
            application.stop_(None)  # type: ignore[attr-defined]
            wake_event = appkit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                appkit.NSEventTypeApplicationDefined,
                (0.0, 0.0),
                0,
                0.0,
                0,
                None,
                0,
                0,
                0,
            )
            application.postEvent_atStart_(wake_event, True)  # type: ignore[attr-defined]

        await run_on_main(stop_run_loop)
