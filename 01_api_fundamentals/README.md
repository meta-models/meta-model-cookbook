# API fundamentals

Ten universal API-primitive recipes for the Meta Model API (Muse Spark). These are the
entry points: each one proves a piece of the API works and gives you a copy-paste starting
point. They use no CLI — just the OpenAI Python SDK pointed at the Model API.

Start with [01 — Chat completions](01_chat_completions.ipynb). It sets up the client,
helpers, and structure that every other recipe reuses, so the concepts in 02–10 build on it.

## Canonical configuration

Every recipe uses exactly this setup. Copy it verbatim; do not vary the base URL, model id,
or key variable.

| Setting | Value |
|---------|-------|
| SDK | OpenAI Python SDK (`from openai import OpenAI`) |
| Base URL | `https://api.meta.ai/v1` |
| Model | `muse-spark-1.1` |
| API key env var | `MODEL_API_KEY` (format `LLM\|{numeric_id}\|{secret}`) |

```python
import os

from openai import OpenAI

# The OpenAI SDK does not auto-read MODEL_API_KEY, so pass it explicitly.
client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"],
)
```

> [!NOTE]
> The official Model API client package is out of date — do not use it. Use the OpenAI SDK.

## The 10 recipes

| # | Recipe | API shape | Demonstrates | Grounded in |
|---|--------|-----------|--------------|-------------|
| [01](01_chat_completions.ipynb) | Chat completions | Chat Completions | OpenAI code works by changing `base_url` + model | [features/chat-completion](https://dev.meta.ai/docs/features/chat-completion) |
| [02](02_streaming.ipynb) | Streaming responses | Chat Completions (`stream=True`) | render tokens as they generate; final usage chunk | [features/chat-completion](https://dev.meta.ai/docs/features/chat-completion) (Streaming) |
| [03](03_tool_calling.ipynb) | Tool / function calling | Chat Completions (`function` tools) | detect `tool_calls`, run the execute→feed-back loop | [features/tool-calling](https://dev.meta.ai/docs/features/tool-calling) |
| [04](04_structured_output.ipynb) | Structured output (JSON mode) | Chat Completions (`response_format`) | schema-guaranteed JSON; Pydantic parse | [features/structured-output](https://dev.meta.ai/docs/features/structured-output) |
| [05](05_prompt_caching.ipynb) | Prompt caching | Chat Completions | reuse a stable prefix; read `cached_tokens` | [features/prompt-caching](https://dev.meta.ai/docs/features/prompt-caching) |
| [06](06_reasoning_tokens.ipynb) | Reasoning / thinking tokens | Chat Completions (`reasoning_effort`) + Responses | control effort; read `reasoning_content`; replay | [features/chat-completion](https://dev.meta.ai/docs/features/chat-completion), [features/responses](https://dev.meta.ai/docs/features/responses) |
| [07](07_vision_input.ipynb) | Vision input | Chat Completions (image content) | send images (URL + base64); structured analysis | [features/image-understanding](https://dev.meta.ai/docs/features/image-understanding) |
| [08](08_long_context.ipynb) | Long context (1M) | Chat Completions | structure repo-level context; 1,048,576-token window | [getting-started/models](https://dev.meta.ai/docs/getting-started/models), [getting-started/overview](https://dev.meta.ai/docs/getting-started/overview) |
| [09](09_error_handling.ipynb) | Error handling & retry | Chat Completions | backoff with jitter; never retry `400` | [getting-started/error-handling](https://dev.meta.ai/docs/getting-started/error-handling), [getting-started/pricing-rate-limits](https://dev.meta.ai/docs/getting-started/pricing-rate-limits) |
| [10](10_search_grounding.ipynb) | Search grounding | Responses (`web_search` tool) | ground answers in live web results; map `url_citation` annotations to footnotes | [features/search-grounding](https://dev.meta.ai/docs/features/search-grounding) |

Work them in order: each recipe is self-contained, but the concepts build on recipe 01.

## Prerequisites

- Python 3.10+.
- A Model API developer account and an API key from [dev.meta.ai](https://dev.meta.ai/).
- The dependencies in this repo's `pyproject.toml` (`openai`, `papermill`, `notebook`, `ipykernel`), installed with `uv sync`.

Set your key once per shell:

```bash
export MODEL_API_KEY="LLM|...|..."
```

In Colab, add `MODEL_API_KEY` to the secrets manager (the key icon in the left sidebar). The
setup cell falls back to it automatically, so the same notebook runs headless and in Colab.

## Running the recipes

These commands run from the repo's `private/` directory.

**Run a recipe headless (verifies every cell against the live API):**

```bash
MODEL_API_KEY="LLM|...|..." uv run papermill \
  api_fundamentals/01_chat_completions.ipynb /tmp/out.ipynb
```

A clean run exits 0 with no error outputs. The run stays well within the
per-team free-tier limits (2,400 requests/min, 800,000 tokens/min).

**Open a recipe interactively:**

```bash
uv run jupyter notebook --no-browser --port 8888 --ip 0.0.0.0
```

**Lint and format (this tree uses ruff, not BLACK/arc):**

```bash
uv tool run ruff check api_fundamentals/
uv tool run ruff format --check api_fundamentals/
```

## Pricing and rate limits

These recipes show token **usage** (`response.usage`) rather than dollar costs. For current
per-token pricing, see [getting-started/pricing-rate-limits](https://dev.meta.ai/docs/getting-started/pricing-rate-limits). Watch the `x-ratelimit-remaining-*`
response headers to throttle before you hit a `429`.
