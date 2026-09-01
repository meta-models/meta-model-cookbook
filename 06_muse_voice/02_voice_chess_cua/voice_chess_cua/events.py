# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Typed, privacy-preserving runtime events and terminal rendering."""

from __future__ import annotations

import math
import re
import sys
import threading
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Protocol, TextIO


class RuntimeEventSeverity(IntEnum):
    DEBUG = 0
    INFO = 1
    NOTICE = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5

    @property
    def label(self) -> str:
        return self.name


class RuntimeStage(StrEnum):
    STARTUP = "startup"
    PERMISSIONS = "permissions"
    CREDENTIALS = "credentials"
    CHESS = "chess"
    VISION = "vision"
    OVERLAY = "overlay"
    AUDIO = "audio"
    ASR = "asr"
    COMMAND_ADMISSION = "command-admission"
    PLANNER = "planner"
    CUA = "cua"
    SHUTDOWN = "shutdown"


class RuntimeEventDeduplication(StrEnum):
    MATERIAL = "material"
    NONE = "none"


class TerminalEventDestination(StrEnum):
    STANDARD_OUTPUT = "stdout"
    STANDARD_ERROR = "stderr"


_SENSITIVE_KEY_FRAGMENTS = (
    "analysis",
    "apikey",
    "audio",
    "bearer",
    "body",
    "chainofthought",
    "content",
    "cookie",
    "credential",
    "header",
    "image",
    "inputtext",
    "instruction",
    "modelinput",
    "modeloutput",
    "modelresponse",
    "outputtext",
    "passphrase",
    "password",
    "payload",
    "pixel",
    "prompt",
    "rawinput",
    "rawoutput",
    "rawresponse",
    "reasoning",
    "responsebody",
    "screenshot",
    "secret",
    "thinking",
    "thought",
    "token",
    "transcript",
    "utterance",
)
_ALLOWED_TEXT_KEYS = frozenset(
    {
        "action",
        "application",
        "category",
        "classification",
        "code",
        "component",
        "destination",
        "endpoint",
        "error_code",
        "lifecycle",
        "method",
        "model",
        "operation",
        "outcome",
        "permission",
        "phase",
        "reason",
        "request_id",
        "session_id",
        "source",
        "square",
        "state",
        "status",
        "transport",
        "type",
        "window_id",
    }
)
_SECRET_PATTERNS = (
    re.compile(r"\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(
        r"\b(authorization|proxy-authorization|api[_ -]?key|apikey|"
        r"access[_ -]?token|refresh[_ -]?token|password|secret|credential)\b"
        r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^,;]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9_+/=-]{40,}\b"),
)


@dataclass(frozen=True, slots=True, init=False)
class RuntimeEventField:
    key: str
    rendered_value: str

    maximum_string_length = 256

    def __init__(self, key: str, value: str | float | bool) -> None:
        safe_key, permits_text, permits_scalar = _safe_field_key(key)
        if isinstance(value, str):
            rendered = (
                _quoted(_safe_field_value(value)) if permits_text else '"<redacted>"'
            )
        else:
            if isinstance(value, bool):
                scalar = "true" if value else "false"
            elif isinstance(value, float):
                scalar = str(value) if math.isfinite(value) else "invalid"
            else:
                scalar = str(value)
            rendered = scalar if permits_scalar else '"<redacted>"'
        object.__setattr__(self, "key", safe_key)
        object.__setattr__(self, "rendered_value", rendered)


@dataclass(frozen=True, slots=True, init=False)
class RuntimeEvent:
    severity: RuntimeEventSeverity
    stage: RuntimeStage
    event: str
    fields: tuple[RuntimeEventField, ...]
    deduplication: RuntimeEventDeduplication

    maximum_field_count = 32

    def __init__(
        self,
        stage: RuntimeStage,
        event: str,
        fields: Iterable[RuntimeEventField] | Mapping[str, str | float | bool] = (),
        severity: RuntimeEventSeverity = RuntimeEventSeverity.INFO,
        deduplication: RuntimeEventDeduplication = RuntimeEventDeduplication.MATERIAL,
    ) -> None:
        normalized_fields: Iterable[RuntimeEventField]
        if isinstance(fields, Mapping):
            normalized_fields = (
                RuntimeEventField(key, fields[key]) for key in sorted(fields)
            )
        else:
            normalized_fields = fields
        object.__setattr__(self, "severity", RuntimeEventSeverity(severity))
        object.__setattr__(self, "stage", RuntimeStage(stage))
        object.__setattr__(self, "event", _safe_event_name(event))
        object.__setattr__(
            self,
            "fields",
            tuple(normalized_fields)[: self.maximum_field_count],
        )
        object.__setattr__(
            self, "deduplication", RuntimeEventDeduplication(deduplication)
        )


class RuntimeEventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None: ...


EventSink = RuntimeEventSink


class DiscardingRuntimeEventSink:
    def emit(self, event: RuntimeEvent) -> None:
        del event


class TerminalEventRenderer:
    def destination(self, severity: RuntimeEventSeverity) -> TerminalEventDestination:
        if severity >= RuntimeEventSeverity.WARNING:
            return TerminalEventDestination.STANDARD_ERROR
        return TerminalEventDestination.STANDARD_OUTPUT

    def render(self, event: RuntimeEvent, at: datetime) -> str:
        prefix = f"{_timestamp(at)} {event.severity.label} [{event.stage.value}] {event.event}"
        if not event.fields:
            return prefix
        fields = " ".join(
            f"{field.key}={field.rendered_value}" for field in event.fields
        )
        return f"{prefix} {fields}"


@dataclass(frozen=True, slots=True)
class TerminalEventDeduplication:
    window_seconds: float = 2.0
    capacity: int = 256

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_seconds", max(0.0, self.window_seconds))
        object.__setattr__(self, "capacity", max(1, self.capacity))


class TerminalEventSink:
    def __init__(
        self,
        renderer: TerminalEventRenderer | None = None,
        standard_output: TextIO = sys.stdout,
        standard_error: TextIO = sys.stderr,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        deduplication: TerminalEventDeduplication | None = None,
    ) -> None:
        self._renderer = renderer or TerminalEventRenderer()
        self._standard_output = standard_output
        self._standard_error = standard_error
        self._now = now
        self._deduplication = deduplication or TerminalEventDeduplication()
        self._last_emitted_at: dict[RuntimeEvent, datetime] = {}
        self._lock = threading.Lock()

    def emit(self, event: RuntimeEvent) -> None:
        with self._lock:
            timestamp = self._now()
            if not self._should_emit(event, timestamp):
                return
            line = self._renderer.render(event, timestamp)
            destination = self._renderer.destination(event.severity)
            handle = (
                self._standard_error
                if destination is TerminalEventDestination.STANDARD_ERROR
                else self._standard_output
            )
            handle.write(f"{line}\n")
            handle.flush()

    def _should_emit(self, event: RuntimeEvent, timestamp: datetime) -> bool:
        if (
            event.deduplication is RuntimeEventDeduplication.NONE
            or self._deduplication.window_seconds <= 0
        ):
            return True
        previous = self._last_emitted_at.get(event)
        if previous is not None:
            elapsed = (timestamp - previous).total_seconds()
            if 0 <= elapsed < self._deduplication.window_seconds:
                return False
        elif len(self._last_emitted_at) >= self._deduplication.capacity:
            oldest = min(self._last_emitted_at, key=self._last_emitted_at.__getitem__)
            del self._last_emitted_at[oldest]
        self._last_emitted_at[event] = timestamp
        return True


def _safe_event_name(raw_value: str) -> str:
    trimmed = raw_value.strip()
    if not trimmed or len(trimmed) > 64 or _looks_like_structured_data(trimmed):
        return "invalid_event"
    redacted = _redact_secrets(trimmed).lower()
    result = re.sub(r"[^a-z0-9._-]+", "_", redacted).strip("._-")
    return result or "invalid_event"


def _safe_field_key(raw_value: str) -> tuple[str, bool, bool]:
    normalized = _identifier(raw_value)
    compact = "".join(
        character for character in raw_value.lower() if character.isalnum()
    )
    is_sensitive = any(fragment in compact for fragment in _SENSITIVE_KEY_FRAGMENTS)
    is_sensitive = is_sensitive or _redact_secrets(raw_value) != raw_value
    if is_sensitive:
        return "redacted_field", False, False
    safe_key = normalized or "field"
    return safe_key, safe_key in _ALLOWED_TEXT_KEYS, True


def _safe_field_value(raw_value: str) -> str:
    trimmed = raw_value.strip()
    if _looks_like_structured_data(trimmed) or _looks_like_encoded_payload(trimmed):
        return "<redacted-structured-data>"
    redacted = _redact_secrets(trimmed)
    without_controls = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in redacted
    )
    single_line = " ".join(without_controls.split())
    return single_line[: RuntimeEventField.maximum_string_length]


def _redact_secrets(raw_value: str) -> str:
    value = _SECRET_PATTERNS[0].sub(r"\1 <redacted>", raw_value)
    value = _SECRET_PATTERNS[1].sub(r"\1=<redacted>", value)
    value = _SECRET_PATTERNS[2].sub("<redacted>", value)
    return _SECRET_PATTERNS[3].sub("<redacted>", value)


def _identifier(raw_value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "_", raw_value.lower()).strip("_")
    return result[:48]


def _looks_like_structured_data(value: str) -> bool:
    return (value.startswith("{") and value.endswith("}")) or (
        value.startswith("[") and value.endswith("]")
    )


def _looks_like_encoded_payload(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("data:", "event:", "image:", "request:", "response:"))


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
