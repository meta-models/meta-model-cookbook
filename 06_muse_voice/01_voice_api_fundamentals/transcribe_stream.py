# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Transcribe live audio over the Muse Voice Transcribe streaming endpoint.

    python transcribe_stream.py sample.wav
    python transcribe_stream.py meeting.wav --mode DIARIZATION
    python transcribe_stream.py --mic                 # Ctrl-C to stop

Audio is paced at real time, so transcripts arrive while the audio is still
uploading. To send a recording all at once instead, see transcribe_file.py.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import wave
from collections.abc import AsyncIterator

from utils import (
    CHUNK_MS,
    DEFAULT_MODE,
    MODES,
    SAMPLE_RATES,
    StreamError,
    chunk_pcm,
    read_wav,
    transcribe_stream,
)

# Queue depth is added latency: a frame waits here before it is sent, so a deep
# queue delays every transcript behind it. Two frames is the floor worth having.
# One would drop audio whenever the loop runs two `_offer` callbacks before the
# consumer is scheduled, which happens under ordinary jitter; two absorbs that
# and nothing more. Note `maxsize=0` means unbounded, not empty.
MIC_QUEUE_FRAMES = 160 // CHUNK_MS


async def mic_chunks(encoding: str) -> AsyncIterator[bytes]:
    """Yield raw PCM from the default input device until cancelled.

    The sounddevice callback runs on its own thread, so it hands chunks over
    with `call_soon_threadsafe`. The queue is an `asyncio.Queue`, so awaiting
    the next chunk yields to the event loop instead of blocking it.

    The queue is bounded. If the sender falls behind real time -- a network
    stall, say -- an unbounded queue would hoard raw PCM for the life of the
    process, and the server would drop the session for slow ingress anyway.
    Discarding the oldest frame keeps memory flat and the stream current.
    """
    import sounddevice as sd  # optional dependency, only needed for --mic

    rate = SAMPLE_RATES[encoding]
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MIC_QUEUE_FRAMES)

    def on_audio(indata, _frames, _time, status) -> None:
        if status:
            print(status, file=sys.stderr)
        loop.call_soon_threadsafe(_offer, bytes(indata))

    def _offer(frame: bytes) -> None:
        if queue.full():
            queue.get_nowait()
            print("microphone buffer full; dropped a frame", file=sys.stderr)
        queue.put_nowait(frame)

    stream = sd.RawInputStream(
        samplerate=rate,
        channels=1,
        dtype="int16",
        blocksize=int(rate * CHUNK_MS / 1000),
        callback=on_audio,
    )
    # Closing the stream on the way out matters: without it the input device
    # stays open until the process exits.
    with stream:
        while True:
            yield await queue.get()


def _clear_line(width: int) -> None:
    """Erase the in-progress partial before printing a permanent line."""
    print(f"\r{' ' * width}\r", end="", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("audio", nargs="?", help="mono 16-bit WAV to stream")
    source.add_argument(
        "--mic", action="store_true", help="stream from the microphone instead"
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=MODES,
        help=(
            f"who decides where an utterance ends "
            f"(default: {DEFAULT_MODE}, or ENDPOINTING with --mic)"
        ),
    )
    parser.add_argument(
        "--encoding",
        default="PCM_24KHZ",
        choices=list(SAMPLE_RATES),
        help="must match the audio's sample rate (default: PCM_24KHZ)",
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

    if args.mic:
        chunks: object = mic_chunks(args.encoding)
        # A microphone already produces audio in real time, so adding a pacer
        # on top would push us behind.
        pace = False
        # Let the model find turn boundaries rather than waiting for endStream.
        # Only when the caller did not ask for a mode: `--mode` defaults to None
        # so an explicit `--mic --mode PUSH_TO_TALK` is still honoured.
        mode = "ENDPOINTING" if args.mode is None else args.mode
        print("Listening. Speak, then press Ctrl-C to finish.", file=sys.stderr)
    elif args.audio:
        try:
            chunks = chunk_pcm(read_wav(args.audio, args.encoding), args.encoding)
        except (ValueError, OSError, wave.Error) as exc:
            print(f"Cannot read {args.audio}: {exc}", file=sys.stderr)
            return 1
        pace = True
        mode = args.mode or DEFAULT_MODE
    else:  # pragma: no cover - argparse rejects this first
        parser.error("pass an audio file, or --mic")

    speaker = None
    width = max(40, shutil.get_terminal_size((100, 24)).columns - 1)
    try:
        async for event in transcribe_stream(
            chunks,
            mode=mode,
            encoding=args.encoding,
            pace=pace,
            keywords=args.keywords,
            language_bias=args.language_bias,
        ):
            kind = event["type"]

            if kind == "session":
                print(f"session {event['sessionId']}", file=sys.stderr)

            elif kind == "transcript":
                # Partials are cumulative: each one replaces the last, so
                # rewrite the line rather than appending to it. Truncate a
                # partial to the terminal width as well as padding to it -- one
                # that is longer wraps onto a second row, and the carriage
                # return then only rewinds that row, so partials would stack
                # instead of overwriting. The final transcript is the result
                # rather than a progress line, so it is printed whole.
                if event["final"]:
                    _clear_line(width)
                    print(event["transcript"])
                else:
                    print(
                        f"{event['transcript'][:width]:<{width}}", end="\r", flush=True
                    )

            elif kind == "speaker":
                # Labels the span of speech that preceded this event. Labels are
                # bare letters -- `A`, `B` -- on both endpoints.
                if event["label"] != speaker:
                    speaker = event["label"]
                    _clear_line(width)
                    print(f"[{speaker}]", flush=True)

            elif kind == "speechComplete":
                # The whole-turn transcript. It arrives asynchronously, so
                # correlate turns by matching turnId, not by arrival order and
                # not by assuming the numbering starts anywhere in particular.
                _clear_line(width)
                print(f"turn {event['turnId']}: {event['transcript'].strip()}")

    except (StreamError, RuntimeError, OSError) as exc:
        # RuntimeError covers a missing MODEL_API_KEY, which is raised before
        # the socket opens. Matches transcribe_file.py so neither CLI answers a
        # setup mistake with a traceback.
        print(f"\n{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
