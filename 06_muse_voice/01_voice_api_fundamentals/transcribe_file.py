# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Transcribe a recording in one request over the Muse Voice Transcribe file endpoint.

    python transcribe_file.py interview.wav
    python transcribe_file.py interview.wav --mode DIARIZATION

Streaming is paced at real time, so a five-minute recording takes five
minutes. This uploads as fast as your connection allows and returns one JSON
response. To watch transcripts arrive live instead, see transcribe_stream.py.
"""

from __future__ import annotations

import argparse
import sys

from utils import DEFAULT_MODE, MODES, TranscribeError, transcribe_recording


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", help="audio file to transcribe")
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        choices=MODES,
        help=f"DIARIZATION also labels who spoke (default: {DEFAULT_MODE})",
    )
    parser.add_argument(
        "--keywords",
        action="append",
        metavar="TERM",
        help="bias recognition toward a term; repeat for several",
    )
    parser.add_argument(
        "--language-bias",
        action="append",
        metavar="LANG",
        help="hint the expected language; repeat for several. Omit to autodetect",
    )
    args = parser.parse_args()

    try:
        result = transcribe_recording(
            args.audio,
            mode=args.mode,
            keywords=args.keywords,
            language_bias=args.language_bias,
        )
    except (TranscribeError, RuntimeError, OSError) as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    # Read every field defensively: `turns` is absent outside the speech modes,
    # and `speaker` is present only in DIARIZATION.
    turns = result.get("turns")
    if turns:
        # Speech modes return the transcript split into turns, with timings.
        # Diarization adds a speaker label to each one.
        for turn in turns:
            who = f"{turn['speaker']}: " if turn.get("speaker") else ""
            start = (turn.get("startMs") or 0) / 1000
            print(f"[{start:7.2f}s] {who}{turn.get('transcript', '')}")
    else:
        print(result.get("transcript", ""))

    duration = (result.get("audioDurationMs") or 0) / 1000
    print(
        f"\n{duration:.1f}s of audio, session {result.get('sessionId')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
