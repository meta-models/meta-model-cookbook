# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import io
import unittest
from datetime import UTC, datetime, timedelta

from voice_chess_cua.events import (
    RuntimeEvent,
    RuntimeEventDeduplication,
    RuntimeEventField,
    RuntimeEventSeverity,
    RuntimeStage,
    TerminalEventDeduplication,
    TerminalEventDestination,
    TerminalEventRenderer,
    TerminalEventSink,
)


class RuntimeEventTests(unittest.TestCase):
    def test_renderer_uses_utc_timestamp_stage_and_sorted_fields(self) -> None:
        event = RuntimeEvent(
            RuntimeStage.ASR,
            "Connection Ready",
            fields={"status": "ready", "attempt": 2},
        )
        renderer = TerminalEventRenderer()
        line = renderer.render(
            event, datetime(2026, 8, 23, 4, 5, 6, 123456, tzinfo=UTC)
        )
        self.assertEqual(
            line,
            '2026-08-23T04:05:06.123Z INFO [asr] connection_ready attempt=2 status="ready"',
        )
        self.assertEqual(
            renderer.destination(RuntimeEventSeverity.INFO),
            TerminalEventDestination.STANDARD_OUTPUT,
        )
        self.assertEqual(
            renderer.destination(RuntimeEventSeverity.WARNING),
            TerminalEventDestination.STANDARD_ERROR,
        )

    def test_sensitive_and_unapproved_text_fields_are_redacted(self) -> None:
        secret = RuntimeEventField("access_token", "top-secret")
        unknown_text = RuntimeEventField("arbitrary", "ambient speech")
        transcript_like_text = RuntimeEventField("text", "Move E2 to E4")
        detail = RuntimeEventField("detail", "server echoed ambient speech")
        structured = RuntimeEventField("reason", '{"payload":"speech"}')
        safe = RuntimeEventField("reason", 'bad "window"\\state')
        controls = RuntimeEventField("detail", "unsafe\x1b[31m bell\x07 nul\x00")
        self.assertEqual(secret.key, "redacted_field")
        self.assertEqual(secret.rendered_value, '"<redacted>"')
        self.assertEqual(unknown_text.rendered_value, '"<redacted>"')
        self.assertEqual(transcript_like_text.rendered_value, '"<redacted>"')
        self.assertEqual(detail.rendered_value, '"<redacted>"')
        self.assertEqual(structured.rendered_value, '"<redacted-structured-data>"')
        self.assertEqual(safe.rendered_value, '"bad \\"window\\"\\\\state"')
        self.assertEqual(controls.rendered_value, '"<redacted>"')

    def test_event_sanitizes_names_and_limits_fields(self) -> None:
        event = RuntimeEvent(
            RuntimeStage.STARTUP,
            '{"raw":"event"}',
            fields=[RuntimeEventField("count", index) for index in range(40)],
        )
        self.assertEqual(event.event, "invalid_event")
        self.assertEqual(len(event.fields), 32)

    def test_terminal_sink_routes_and_deduplicates_material_events(self) -> None:
        output = io.StringIO()
        error = io.StringIO()
        current = [datetime(2026, 8, 23, tzinfo=UTC)]
        sink = TerminalEventSink(
            standard_output=output,
            standard_error=error,
            now=lambda: current[0],
            deduplication=TerminalEventDeduplication(window_seconds=2),
        )
        event = RuntimeEvent(RuntimeStage.COMMAND_ADMISSION, "admitted")
        sink.emit(event)
        sink.emit(event)
        current[0] += timedelta(seconds=2)
        sink.emit(event)
        sink.emit(
            RuntimeEvent(
                RuntimeStage.CUA,
                "blocked",
                severity=RuntimeEventSeverity.ERROR,
                deduplication=RuntimeEventDeduplication.NONE,
            )
        )
        self.assertEqual(output.getvalue().count("[command-admission] admitted"), 2)
        self.assertIn("ERROR [cua] blocked", error.getvalue())


if __name__ == "__main__":
    unittest.main()
