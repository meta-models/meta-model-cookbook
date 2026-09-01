# Speech to text

|  |  |
|---|---|
| **Section** | [Muse Voice Transcribe](../) |
| **Docs** | [Speech to text](https://dev.meta.ai/docs/speech-to-text) · [API reference](https://dev.meta.ai/docs/api-reference/voice) |
| **Time to complete** | ~10 min |
| **Model** | `muse-voice-transcribe-1.0` |
| **Language** | Python |
| **Prerequisites** | Python 3.10+, the `websockets` and `requests` packages, a `MODEL_API_KEY`, and a mono 16-bit WAV. [ffmpeg](https://ffmpeg.org/) to convert audio, and [sounddevice](https://pypi.org/project/sounddevice/) for microphone input. |

Muse Voice Transcribe turns speech into text across 25 languages, and the model handles punctuation, speech-boundary detection and speaker attribution itself.

There are two ways to use it, and this recipe demonstrates both:

| Script | Endpoint | Use it when |
|---|---|---|
| `transcribe_stream.py` | `wss://api.meta.ai/v1/asr/realtime` | You want transcripts while the speaker is still talking — a microphone, a call, or a file played at real time. |
| `transcribe_file.py` | `https://api.meta.ai/v1/asr/transcribe` | You already have a recording and just want the text back as fast as it uploads. |

Shared client code for both lives in `utils.py`.

## Setup

```bash
pip install websockets requests
export MODEL_API_KEY="<your Model API key>"
```

Both scripts take the same input: a **mono 16-bit WAV** at 24 kHz (engine-native) or 16 kHz. The sampling is identical either way; only the transport differs. The streaming endpoint receives the raw PCM frames read out of that file, which is what the `PCM_24KHZ` and `PCM_16KHZ` encoding names refer to, while the one-shot endpoint uploads the WAV itself. Convert anything else first:

```bash
ffmpeg -i input.mp3 -ac 1 -ar 24000 -sample_fmt s16 sample.wav
```

## Stream a recording

```bash
python transcribe_stream.py sample.wav
```

```
session 89465FD9A818F4B89CBA1501C4A4C1BC
Where is the capital of Switzerland?
```

Watch it live and the transcript builds and revises itself: `Where` → `Where is the` → `Where is the capital of` → `Where is the capital of Switzerland?`

Partials are **cumulative** — each one replaces the last, so render in place rather than appending. The `final: true` frame is the completion signal.

## Dictate from a microphone

```bash
pip install sounddevice
python transcribe_stream.py --mic
```

Two things change. It defaults to `ENDPOINTING` so the model finds turn boundaries instead of waiting for you to declare them — pass `--mode` explicitly to override that — and it drops the pacer, because a microphone already produces audio in real time.

## Attribute speech to speakers with diarization

```bash
python transcribe_stream.py meeting.wav --mode DIARIZATION
```

```
[A]
turn 0: What do we got? Let's see, a couple of different health trackers...
[B]
turn 1: But first, did they even test this? I have one for YouTube.
```

The turn lifecycle is `speechStart` → partials → `speaker` → `speechEnd` → `speechComplete`. A `speaker` event labels the span *before* it, and `speechComplete` arrives asynchronously, so correlate by `turnId` rather than by arrival order. Diarization covers non-overlapping speech.

## Transcribe a recording in one request

```bash
python transcribe_file.py interview.wav --mode DIARIZATION
```

```
[   1.52s] A: How is the weather?
[   5.90s] B: It is raining.
```

One HTTP `POST`, one JSON response carrying the whole transcript plus a `turns` array. Two differences from the streaming endpoint catch people out: the credential goes in an `Authorization` **header** rather than inside the handshake, and there is no pacing — you upload as fast as your connection allows.

Speaker labels are bare letters on both endpoints, so a turn carries `"speaker": "A"`, not `speaker_a`.

## Modes

| Mode | Who ends the turn | Use it for |
|---|---|---|
| `PUSH_TO_TALK` | You do | Push-to-talk, transcribing a file |
| `ENDPOINTING` | The model detects speech start and end | Live dictation, voice agents |
| `DIARIZATION` | The model, plus speaker labels | Meetings, interviews, calls |

Both endpoints share these three names, and `PUSH_TO_TALK` is the default on each. Mode is fixed at the handshake and cannot change mid-session. Not every model serves every mode, and asking for one it does not serve is rejected before any audio is accepted.

## Bias the transcription

Both endpoints accept two optional biasing parameters, and each script exposes one flag per parameter. Both parameters are lists of strings, so repeat a flag to send several values.

```bash
python transcribe_stream.py standup.wav --keywords Anaya --keywords Kolkata
python transcribe_file.py interview.wav --language-bias english
```

`--keywords` populates the endpoint's `keywords` parameter — use it for names, jargon, and product words the model would otherwise mis-hear. `--language-bias` populates `languageBias` — use it when you already know the language. Both nudge the model rather than constrain it, so neither guarantees an exact spelling.

## Cutoff behaviour

| What the server checks | Close code |
|---|---|
| No handshake within 10 seconds | `1008` |
| More than 5 seconds of audio backlog, so don't blast a file at full speed | `1008` |
| Ingress below real time for 10 seconds, so pad silence during gaps | `1008` |
| Streaming session open longer than 60 minutes | `1011` |
| Rate limited | `1013` |

The model has a streaming cap of 60 minutes. The one-shot endpoint is capped at 10 minutes of audio or 32 MB, whichever comes first.

The pacing rules cut both ways, which is why the client paces against an absolute schedule rather than sleeping a fixed amount per chunk. Sleep a flat interval and every slow send adds drift, until ten seconds of accumulated lateness closes the session.
