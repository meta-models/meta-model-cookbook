# Muse Voice Transcribe

Recipes for building with [Muse Voice Transcribe](https://dev.meta.ai/docs/speech-to-text), the streaming speech-to-text model on the Meta Model API. The full contract lives in the [API reference](https://dev.meta.ai/docs/api-reference/voice). Speech goes in over a WebSocket and transcripts come back while the speaker is still talking, with punctuation, speech-boundary detection and speaker attribution handled by the model rather than by extra components in your pipeline.

There are two ways in. `/v1/asr/realtime` is a WebSocket for live audio, and the one part of the Model API that is not an HTTP endpoint — real-time transcription needs a bidirectional connection, so these recipes use a WebSocket client rather than the OpenAI SDK. `/v1/asr/transcribe` is a plain HTTP `POST` for a recording you already have. Same models, same three modes, different transport.

## Recipes

| # | Recipe | What it does |
|---|--------|--------------|
| [01](01_voice_api_fundamentals/) | Speech to text | Transcribe a recording or a live microphone over the streaming WebSocket, get speaker-attributed turns with diarization, or post a whole recording in one HTTP request. |

## Configuration

A Model API key is the only thing these recipes need:

```bash
export MODEL_API_KEY="<your Model API key>"
```
