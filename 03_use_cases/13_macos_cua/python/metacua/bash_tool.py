"""The `bash` computer-use tool: run a bounded shell command."""

import signal
import subprocess
from typing import Tuple

from .errors import CLIError

_BASH_TOOL_MAX_OUTPUT_BYTES = 128 * 1024


def _truncate(data: bytes) -> Tuple[str, int]:
    """Cap captured output to the byte budget and report how much was dropped."""
    dropped = max(0, len(data) - _BASH_TOOL_MAX_OUTPUT_BYTES)
    kept = data[:_BASH_TOOL_MAX_OUTPUT_BYTES]
    text = kept.decode("utf-8", errors="replace")
    return text, dropped


def run_bash_tool(command: str, timeout_ms: int) -> str:
    trimmed = command.strip()
    if not trimmed:
        raise CLIError("bash command must not be empty")

    process = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    timed_out = False
    try:
        out_data, err_data = process.communicate(timeout=timeout_ms / 1000.0)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        try:
            out_data, err_data = process.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                out_data, err_data = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                out_data, err_data = b"", b""

    exit_code = process.returncode if process.returncode is not None else -signal.SIGKILL

    result = _format_bash_tool_result(
        command=trimmed,
        timeout_ms=timeout_ms,
        timed_out=timed_out,
        exit_code=exit_code,
        stdout=_truncate(out_data or b""),
        stderr=_truncate(err_data or b""),
    )

    if timed_out or exit_code != 0:
        raise CLIError(result)
    return result


def _format_bash_tool_result(
    command: str,
    timeout_ms: int,
    timed_out: bool,
    exit_code: int,
    stdout: Tuple[str, int],
    stderr: Tuple[str, int],
) -> str:
    parts = [f"command: {command}"]
    if timed_out:
        parts.append(f"status: timed out after {timeout_ms}ms")
    else:
        parts.append(f"status: exit {exit_code}")
    parts.append(_format_stream("stdout", stdout))
    parts.append(_format_stream("stderr", stderr))
    return "\n".join(parts)


def _format_stream(name: str, stream: Tuple[str, int]) -> str:
    text, dropped = stream
    rendered = text.strip("\n")
    rendered = rendered if rendered else "<empty>"
    if dropped > 0:
        return f"{name}:\n{rendered}\n[{dropped} byte(s) truncated]"
    return f"{name}:\n{rendered}"
