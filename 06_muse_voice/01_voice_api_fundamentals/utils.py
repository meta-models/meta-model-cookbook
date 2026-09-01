# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Shared client code for the two Muse Voice Transcribe endpoints.

`transcribe_stream()` streams audio over the realtime WebSocket and yields
events as they arrive. `transcribe_recording()` posts a whole recording to the
one-shot HTTP endpoint and returns a single response.

Both are used by the two CLIs in this recipe: `transcribe_stream.py` and
`transcribe_file.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import wave
from collections.abc import AsyncIterator, Iterable
from typing import Any

import requests
import websockets

# The engine is native at 24 kHz; 16 kHz is accepted and resampled server-side.
SAMPLE_RATES: dict[str, int] = {"PCM_16KHZ": 16000, "PCM_24KHZ": 24000}

# How much audio to put in each binary frame. Frame boundaries carry no meaning
# to the server, but smaller frames lower latency. This matches the backend's
# 80 ms processing chunk; the server does not require it and may change that
# cadence, so do not depend on the two staying equal.
CHUNK_MS = 80

# Both endpoints are served from the Model API host.
DEFAULT_STREAM_URL = "wss://api.meta.ai/v1/asr/realtime"
DEFAULT_TRANSCRIBE_URL = "https://api.meta.ai/v1/asr/transcribe"

# The public model name.
DEFAULT_MODEL = "muse-voice-transcribe-1.0"

# Both endpoints share one Mode enum, so the same three names work on each.
# `PUSH_TO_TALK` is the default: the caller delimits the turn, by ending the
# stream or by uploading a whole clip. Keep the CLIs' `--mode` choices bound to
# this tuple -- the server ignores an unrecognised mode rather than rejecting
# it, so a stale name would silently transcribe in the wrong mode.
MODES = ("PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION")
DEFAULT_MODE = MODES[0]

# --- One-shot request details -----------------------------------------------

# The one-shot endpoint reads an Authorization header, unlike the streaming
# handshake which carries the credential in JSON.
AUTH_SCHEME = "Bearer"

AUDIO_FORMAT_FIELD = "audioEncoding"
AUDIO_FORMAT_VALUE = "WAV"

# 10 minutes of audio, or 32 MB, whichever comes first. A realtime session is
# capped separately and far higher. Oversized bodies return 413; over-long
# audio returns 400 once the server has decoded it.
MAX_BYTES = 32 * 1024 * 1024


class TranscribeError(RuntimeError):
    """The server rejected the request or failed to transcribe it."""


class StreamError(RuntimeError):
    """The server sent an error event or closed the session abnormally."""


def read_wav(path: str, encoding: str = "PCM_24KHZ") -> bytes:
    """Read a mono 16-bit WAV whose sample rate matches `encoding`.

    The API takes raw PCM with no container, so this strips the WAV header and
    hands back the sample data. Converting other formats is a job for ffmpeg,
    not this client -- see the recipe README.
    """
    want = SAMPLE_RATES[encoding]
    with wave.open(path, "rb") as w:
        channels, width, rate, frames = (
            w.getnchannels(),
            w.getsampwidth(),
            w.getframerate(),
            w.getnframes(),
        )
        data = w.readframes(frames)

    problems = []
    if channels != 1:
        problems.append(f"{channels} channels (need mono)")
    if width != 2:
        problems.append(f"{width * 8}-bit samples (need 16-bit)")
    if rate != want:
        problems.append(f"{rate} Hz (need {want} Hz for {encoding})")
    if problems:
        raise ValueError(
            f"{path}: {', '.join(problems)}. Convert it with:\n"
            f"  ffmpeg -i {path} -ac 1 -ar {want} -sample_fmt s16 converted.wav"
        )
    return data


def chunk_pcm(
    pcm: bytes, encoding: str = "PCM_24KHZ", chunk_ms: int = CHUNK_MS
) -> Iterable[bytes]:
    """Split raw PCM into fixed-duration chunks."""
    size = int(SAMPLE_RATES[encoding] * 2 * chunk_ms / 1000)
    for i in range(0, len(pcm), size):
        yield pcm[i : i + size]


def _normalize(frame: dict[str, Any]) -> dict[str, Any]:
    """Return every server frame as a flat `type`-tagged dict.

    Events arrive internally tagged, e.g. `{"type": "transcript", ...}`. The
    handshake response is the exception: it is a struct rather than a union, so
    it comes back as a bare `{"sessionId": "..."}` with no `type`.
    """
    if "type" in frame:
        return frame
    if "sessionId" in frame:
        return {"type": "session", "sessionId": frame["sessionId"]}
    return {"type": "unknown", **frame}


def _closed(exc: Exception) -> StreamError | None:
    """Turn an abnormal close into an error that says what to do about it.

    Returns None for a clean 1000 close, which is how a finished session ends
    and not something the caller should hear about.
    """
    code = getattr(exc, "code", None)
    if code == 1000:
        return None
    reason = (getattr(exc, "reason", "") or "").strip()
    advice = {
        1008: "bad request, or audio was paced too slowly or too fast",
        1011: "server error, or the maximum session duration was reached",
        1013: "rate limited; back off and reconnect",
    }.get(code, "connection closed unexpectedly")
    detail = f": {reason}" if reason else ""
    return StreamError(f"[{code}] {advice}{detail}")


async def _as_async(chunks: Any) -> AsyncIterator[bytes]:
    """Iterate either a sync iterable or an async one.

    A file reader is a plain generator. A live microphone is better modelled as
    an async iterator, so that waiting for the next chunk yields to the event
    loop instead of blocking every other task on it.
    """
    if hasattr(chunks, "__aiter__"):
        async for chunk in chunks:
            yield chunk
    else:
        for chunk in chunks:
            yield chunk


async def _send_audio(
    ws: Any, chunks: Any, *, pace: bool, encoding: str, end_frame: str
) -> None:
    """Stream audio, then half-close the input.

    Runs as a background task so the caller can read events while this uploads.
    """
    # Derive elapsed audio from the bytes actually sent rather than assuming
    # every chunk is full-sized: the last chunk of a file usually is not, and a
    # caller may hand us variable-sized ones.
    bytes_per_second = SAMPLE_RATES[encoding] * 2
    started = time.monotonic()
    elapsed_audio = 0.0
    async for chunk in _as_async(chunks):
        await ws.send(chunk)  # binary frame
        elapsed_audio += len(chunk) / bytes_per_second
        if pace:
            # Pace against an absolute schedule rather than sleeping a fixed
            # amount per chunk: that way slow sends catch up instead of
            # drifting further behind and tripping the real-time monitor.
            behind = started + elapsed_audio - time.monotonic()
            if behind > 0:
                await asyncio.sleep(behind)

    # Pausing is not enough: this half-closes the audio input while leaving the
    # socket open for the events still in flight.
    await ws.send(end_frame)


async def transcribe_stream(
    chunks: Any,
    *,
    token: str | None = None,
    model: str | None = None,
    mode: str = DEFAULT_MODE,
    encoding: str = "PCM_24KHZ",
    url: str | None = None,
    pace: bool = True,
    keywords: list[str] | None = None,
    language_bias: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream `chunks` of raw PCM and yield transcript events as they arrive.

    Args:
        chunks: Iterable of raw PCM byte strings, in the format named by
            `encoding`. Either a plain iterable or an async one.
        token: Session credential. Defaults to `$MODEL_API_KEY`.
        model: Public model name. Defaults to `DEFAULT_MODEL`.
        mode: `PUSH_TO_TALK` (you decide when the utterance ends),
            `ENDPOINTING` (the model detects speech boundaries), or
            `DIARIZATION` (endpointing plus speaker labels).
        encoding: `PCM_24KHZ` or `PCM_16KHZ`.
        url: Streaming endpoint. Defaults to `DEFAULT_STREAM_URL`.
        pace: Sleep between chunks so audio is sent at roughly real time. Leave
            this on for file playback; turn it off for live microphone input,
            which is already real time.
        keywords: Terms to bias recognition toward -- names, jargon, product
            words the model would otherwise mis-hear.
        language_bias: Hints about the expected language. Omit to let the model
            detect it.

    Yields:
        Flat event dicts, each with a `type` key. See the recipe README for the
        full event list.
    """
    token = token or os.environ.get("MODEL_API_KEY")
    if not token:
        raise RuntimeError("Set MODEL_API_KEY to your Model API key.")
    model = model or DEFAULT_MODEL

    handshake = {
        "mode": mode,
        # The credential rides inside the handshake JSON rather than in an HTTP
        # `Authorization` header, because a browser cannot set headers on a
        # WebSocket. An unrecognised token is rejected here, before any audio.
        "authorization": {"accessToken": token},
        # Enum fields travel as their NAME string, never a number.
        "audioEncoding": encoding,
        "model": model,
        # Each partial replaces the last, which is what the CLIs render in
        # place. `DELTA` is also accepted, but this recipe does not use it.
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
    }
    # Both are optional, and only sent when set: the server ignores
    # unrecognised handshake fields silently, so an empty value would look
    # identical to a working one and hide a typo.
    if keywords:
        handshake["keywords"] = keywords
    if language_bias:
        handshake["languageBias"] = language_bias

    resolved_url = url or DEFAULT_STREAM_URL
    async with websockets.connect(resolved_url, max_size=None) as ws:
        await ws.send(json.dumps(handshake))

        # Read the handshake response before sending any audio. The server
        # always answers the handshake first, so a rejected one (unknown model,
        # unsupported mode, bad credential) surfaces here as a clean error
        # rather than as a closed socket midway through the upload.
        try:
            ack = _normalize(json.loads(await ws.recv()))
        except websockets.exceptions.ConnectionClosed as exc:
            raise (
                _closed(exc) or StreamError("closed before the handshake response")
            ) from exc
        if ack["type"] == "error":
            raise StreamError(ack.get("message", "handshake rejected"))
        yield ack

        # Upload in the background so the loop below surfaces transcripts while
        # audio is still being sent. Sending everything first and reading
        # afterwards produces the same final transcript, but none of it arrives
        # until the whole clip has been uploaded -- which for a real recording
        # means no output at all until the end.
        sender = asyncio.create_task(
            _send_audio(
                ws,
                chunks,
                pace=pace,
                encoding=encoding,
                end_frame=json.dumps({"type": "endStream"}),
            )
        )
        # Set only when this function deliberately raises, so the `finally`
        # below can tell "we are already reporting a failure" from "the
        # generator is being torn down". Checking `sys.exc_info()` instead
        # would also see a `GeneratorExit` -- raised when a consumer breaks out
        # of the loop early -- and silently drop a real upload error.
        reporting = False
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                event = _normalize(json.loads(message))
                if event["type"] == "error":
                    reporting = True
                    raise StreamError(event.get("message", "unknown transcription error"))
                yield event
        except websockets.exceptions.ConnectionClosed as exc:
            failure = _closed(exc)
            if failure:
                reporting = True
                raise failure from exc
        finally:
            # Surface an upload failure rather than letting it vanish with the
            # cancelled task, unless we are already reporting one -- raising
            # from a `finally` replaces the original exception and would hide
            # the more informative one.
            sender.cancel()
            upload = (await asyncio.gather(sender, return_exceptions=True))[0]
            if not reporting and isinstance(upload, BaseException):
                if isinstance(upload, websockets.exceptions.ConnectionClosed):
                    failure = _closed(upload)
                    if failure:
                        raise failure from upload
                elif not isinstance(upload, asyncio.CancelledError):
                    raise upload


def transcribe_recording(
    path: str,
    *,
    mode: str = DEFAULT_MODE,
    model: str | None = None,
    token: str | None = None,
    keywords: list[str] | None = None,
    language_bias: list[str] | None = None,
    session_id: str | None = None,
    url: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """POST a recording and return the parsed JSON response.

    Args:
        path: Path to the audio file.
        mode: `PUSH_TO_TALK`, `ENDPOINTING`, or `DIARIZATION`.
        model: Public model name. Defaults to `DEFAULT_MODEL`.
        token: Credential. Defaults to `$MODEL_API_KEY`.
        keywords: Terms to bias recognition toward -- names, jargon, product
            words the model would otherwise mis-hear.
        language_bias: Hints about the expected language. Omit to let the model
            detect it.
        session_id: Correlation id, sent as a query param so it is known before
            the (potentially large) body finishes uploading.
        url: One-shot endpoint. Defaults to `DEFAULT_TRANSCRIBE_URL`.
        timeout: Seconds to wait. A 10-minute recording needs a generous value.

    Returns:
        `{"sessionId", "transcript", "audioDurationMs", "turns": [...]}`.
        `turns` is present only in the speech modes, and each turn carries
        `speaker` only in `DIARIZATION`.
    """
    token = token or os.environ.get("MODEL_API_KEY")
    if not token:
        raise RuntimeError("Set MODEL_API_KEY to your Model API key.")
    model = model or DEFAULT_MODEL

    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise TranscribeError(
            f"{path} is {size / 1024 / 1024:.1f} MB; the limit is 32 MB. "
            "Split the recording, or stream it through /v1/asr/realtime instead."
        )

    request: dict[str, Any] = {
        "mode": mode,
        "model": model,
        AUDIO_FORMAT_FIELD: AUDIO_FORMAT_VALUE,
    }
    if keywords:
        request["keywords"] = keywords
    if language_bias:
        request["languageBias"] = language_bias

    with open(path, "rb") as audio:
        response = requests.post(
            url or DEFAULT_TRANSCRIBE_URL,
            params={"sessionId": session_id} if session_id else None,
            headers={"Authorization": f"{AUTH_SCHEME} {token}"},
            files={
                # The params travel as a JSON part, not as form fields.
                "request": (None, json.dumps(request), "application/json"),
                "audio": (os.path.basename(path), audio),
            },
            timeout=timeout,
        )

    if response.status_code != 200:
        hint = {
            400: "audio longer than the 10-minute cap, or a malformed request",
            401: "the credential was not accepted",
            404: "endpoint not found",
            413: "body over 32 MB",
            429: "rate limited; back off and retry",
            500: "the server exceeded its processing budget",
        }.get(response.status_code, "unexpected response")
        raise TranscribeError(f"[{response.status_code}] {hint}: {response.text[:300]}")

    return response.json()
