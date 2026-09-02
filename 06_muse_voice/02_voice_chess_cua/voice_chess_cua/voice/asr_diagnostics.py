# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Privacy-safe structural diagnostics for realtime ASR transport failures."""

from __future__ import annotations

import ssl
from enum import StrEnum
from typing import Any

from websockets.exceptions import ConnectionClosed


class ASRClientError(RuntimeError):
    """Base error for ASR transport failures."""


class ASRTransportPhase(StrEnum):
    WEBSOCKET_CONNECT = "websocket_connect"
    HANDSHAKE_EXCHANGE = "handshake_exchange"


class ASRTransportError(ASRClientError):
    """A transport failure with a fixed phase and no embedded cause details."""

    def __init__(self, phase: ASRTransportPhase) -> None:
        self.phase = phase
        super().__init__(
            "ASR WebSocket connection failed."
            if phase is ASRTransportPhase.WEBSOCKET_CONNECT
            else "ASR handshake transport failed."
        )

    @property
    def reason(self) -> str:
        if self.phase is ASRTransportPhase.WEBSOCKET_CONNECT:
            return "websocket_connect_failed"
        return "handshake_transport_failed"


def safe_transport_diagnostics(error: ASRTransportError) -> dict[str, str | int]:
    """Return bounded structural metadata without exception text or wire data."""
    fields: dict[str, str | int] = {
        "reason": error.reason,
        "transport": error.phase.value,
    }
    cause = error.__cause__
    if cause is None:
        fields["classification"] = "transport_error"
        return fields

    status = _http_status(cause)
    if status is not None:
        fields["classification"] = "http_rejected"
        fields["status"] = status
        return fields

    if isinstance(cause, ConnectionClosed):
        fields["classification"] = "websocket_closed"
        code = _close_code(cause)
        if code is not None:
            fields["code"] = code
        return fields

    if isinstance(cause, ssl.SSLCertVerificationError):
        fields["classification"] = "tls_verification_failed"
        verify_code = getattr(cause, "verify_code", None)
        if _is_int(verify_code):
            fields["error_code"] = verify_code
        return fields

    if isinstance(cause, TimeoutError):
        fields["classification"] = "timed_out"
        return fields

    if isinstance(cause, OSError):
        fields["classification"] = "network_error"
        if _is_int(cause.errno):
            fields["error_code"] = cause.errno
        return fields

    fields["classification"] = "transport_error"
    return fields


def _http_status(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if _is_int(status):
        return status
    response: Any = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return status if _is_int(status) else None


def _close_code(error: ConnectionClosed) -> int | None:
    code = getattr(error, "code", None)
    if _is_int(code):
        return code
    received: Any = getattr(error, "rcvd", None)
    code = getattr(received, "code", None)
    return code if _is_int(code) else None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
