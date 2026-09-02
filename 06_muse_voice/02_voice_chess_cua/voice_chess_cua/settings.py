# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Validated fixed runtime settings and safety constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

DEFAULT_ASR_ENDPOINT = "wss://api.meta.ai/v1/asr/realtime"
DEFAULT_ASR_MODEL = "muse-voice-transcribe-1.0"
DEFAULT_COMMAND_LOCALE = "en-US"
MODEL_API_KEY_ENVIRONMENT = "MODEL_API_KEY"

_LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")


class SettingsValidationError(ValueError):
    pass


class InvalidEndpointError(SettingsValidationError):
    pass


class MissingModelError(SettingsValidationError):
    pass


class InvalidCommandLocaleError(SettingsValidationError):
    pass


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    minimum_board_confidence: float = 0.85
    required_stable_detections: int = 2
    maximum_detection_age_seconds: float = 0.5
    maximum_corner_drift_fraction: float = 0.01
    click_delay_seconds: float = 0.15
    activation_timeout_seconds: float = 3.0
    maximum_buffered_audio_duration_seconds: float = 2.0


STANDARD_SAFETY_POLICY = SafetyPolicy()


@dataclass(frozen=True, slots=True)
class AppSettings:
    endpoint: str = DEFAULT_ASR_ENDPOINT
    model: str = DEFAULT_ASR_MODEL
    command_locale_identifier: str = DEFAULT_COMMAND_LOCALE
    client_identity_label: str = ""

    def validated(self) -> AppSettings:
        try:
            components = urlsplit(self.endpoint)
        except (TypeError, ValueError) as error:
            raise InvalidEndpointError(
                "The ASR endpoint must be a valid secure WebSocket URL."
            ) from error
        if (
            components.scheme.lower() != "wss"
            or not components.hostname
            or self.endpoint != DEFAULT_ASR_ENDPOINT
        ):
            raise InvalidEndpointError(
                "The ASR endpoint must be the fixed Meta Model API secure WebSocket URL."
            )
        if self.model != DEFAULT_ASR_MODEL:
            raise MissingModelError(
                "The ASR model must be the fixed public Muse Voice Transcribe model."
            )
        normalized_locale = self.command_locale_identifier.strip()
        if not normalized_locale or not _LOCALE_PATTERN.fullmatch(normalized_locale):
            raise InvalidCommandLocaleError("A valid local command locale is required.")
        return replace(
            self,
            command_locale_identifier=normalized_locale,
            client_identity_label=self.client_identity_label.strip(),
        )
