# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Command-line entry point for the Voice Chess recipe."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import signal
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol, TextIO, cast

USAGE = """Usage: voice-chess [--dry-run]
       voice-chess --request-permissions

Control Apple Chess with exact spoken move commands.

Options:
  --dry-run              Validate moves without posting native input.
  --request-permissions  Request required macOS privacy permissions and exit.
  -h, --help             Show this help message.

Validated execution is automatic by default. Set MODEL_API_KEY before running."""


class CLIExitCode(IntEnum):
    SUCCESS = 0
    USAGE = 2
    CONFIGURATION = 3
    PERMISSION = 4
    CHESS_UNAVAILABLE = 5
    AUDIO_OR_TRANSCRIPTION = 6
    COMMAND = 7
    AUTOMATION = 8
    INTERNAL_ERROR = 70
    INTERRUPTED = 130
    TERMINATED = 143

    @classmethod
    def for_signal(cls, signal_number: int) -> CLIExitCode:
        if signal_number == signal.SIGINT:
            return cls.INTERRUPTED
        if signal_number == signal.SIGTERM:
            return cls.TERMINATED
        return cls.INTERNAL_ERROR


class CommandName(StrEnum):
    RUN = "run"
    REQUEST_PERMISSIONS = "request-permissions"
    HELP = "help"


@dataclass(frozen=True, slots=True)
class CLICommand:
    name: CommandName
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class CLIInvocation:
    command: CLICommand


class CLIParseError(ValueError):
    pass


class CLIServiceLoadError(RuntimeError):
    pass


class CommandServices(Protocol):
    def execute(
        self,
        invocation: CLIInvocation,
    ) -> CLIExitCode | int | Awaitable[CLIExitCode | int]: ...


def load_default_services() -> CommandServices:
    """Load native runtime services only after a run command is parsed."""

    try:
        module = importlib.import_module("voice_chess_cua.runtime.services")
        builder = cast(Callable[[], CommandServices], module.build_command_services)
    except (AttributeError, ImportError) as error:
        raise CLIServiceLoadError(
            "Voice Chess runtime services are unavailable."
        ) from error
    return builder()


def parse_args(arguments: Sequence[str]) -> CLICommand:
    args = tuple(arguments)
    if args in {("help",), ("-h",), ("--help",)}:
        return CLICommand(CommandName.HELP)
    if args == ("--request-permissions",):
        return CLICommand(CommandName.REQUEST_PERMISSIONS)

    allowed = {"--dry-run"}
    if any(argument not in allowed for argument in args) or len(set(args)) != len(args):
        raise CLIParseError("Invalid arguments.")
    return CLICommand(
        CommandName.RUN,
        dry_run="--dry-run" in args,
    )


def main(
    argv: Sequence[str] | None = None,
    services: CommandServices | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    try:
        command = parse_args(arguments)
    except CLIParseError as error:
        print(f"Error: {error}\n\n{USAGE}", file=stderr)
        return int(CLIExitCode.USAGE)

    if command.name is CommandName.HELP:
        print(USAGE, file=stdout)
        return int(CLIExitCode.SUCCESS)

    try:
        active_services = services if services is not None else load_default_services()
        result = active_services.execute(CLIInvocation(command=command))
        if inspect.isawaitable(result):
            return _normalize_exit_code(asyncio.run(_await_service_result(result)))
        return _normalize_exit_code(result)
    except CLIServiceLoadError as error:
        print(f"Error: {error}", file=stderr)
        return int(CLIExitCode.INTERNAL_ERROR)
    except KeyboardInterrupt:
        return int(CLIExitCode.INTERRUPTED)
    except Exception:  # noqa: BLE001 - classify unknown failures at the process boundary.
        print("Error: An unexpected internal failure occurred.", file=stderr)
        return int(CLIExitCode.INTERNAL_ERROR)


async def _await_service_result(
    result: Awaitable[CLIExitCode | int],
) -> CLIExitCode | int:
    return await result


def _normalize_exit_code(value: CLIExitCode | int) -> int:
    if isinstance(value, bool):
        raise TypeError("command service returned an invalid exit code")
    try:
        return int(CLIExitCode(value))
    except (TypeError, ValueError) as error:
        raise ValueError("command service returned an invalid exit code") from error
