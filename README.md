# Meta Model API cookbook

Recipes for building agents and coding tools on the Meta Model API, covering API fundamentals,
agent patterns, and end-to-end use cases.

Meta Model API lets you build with Muse Spark using the
tools you already run: it's drop-in compatible with the OpenAI
SDK, the Anthropic SDK, and agent CLIs like OpenCode and Claude Code.

Point your client at
the Model API base URL, set your key, and keep the rest of your code. Each recipe is a
self-contained, copy-paste starting point that proves a capability and gives you something to build
on. The default model is **Muse Spark** (`muse-spark-1.1`), which has a 1,048,576-token context
window; the preview is free.

## Getting started

You need a [Model API account](https://dev.meta.ai/) and an API key. Store the key as
an environment variable so it stays out of your code:

```bash
export MODEL_API_KEY="LLM|{numeric_id}|{secret}"
pip install openai
```

```python
import os

from openai import OpenAI

# The OpenAI SDK does not auto-read MODEL_API_KEY, so pass it explicitly.
client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"],
)

response = client.chat.completions.create(
    model="muse-spark-1.1",
    messages=[{"role": "user", "content": "Hello, world!"}],
)

print(response.choices[0].message.content)
```

## Recipes

This cookbook mirrors the three sections of the Meta Model API cookbook website. Each recipe
is a self-contained, copy-paste starting point. Start with **API fundamentals** to learn the
API primitives, then move into **agent patterns** and end-to-end **use cases**.

### [1. API fundamentals](01_api_fundamentals/)

Prove each API primitive works and get a starting point you can build on.

| # | Recipe | What it does |
|---|--------|--------------|
| 01 | [Quickstart: chat completions](01_api_fundamentals/01_chat_completions.ipynb) | Make your first Muse Spark call by pointing the OpenAI SDK at one new base URL. |
| 02 | [Streaming responses](01_api_fundamentals/02_streaming.ipynb) | Render tokens as they generate and read the final usage chunk. |
| 03 | [Tool and function calling](01_api_fundamentals/03_tool_calling.ipynb) | Detect tool calls and run the execute-and-feed-back loop. |
| 04 | [Structured output](01_api_fundamentals/04_structured_output.ipynb) | Get schema-guaranteed JSON that parses on the first try. |
| 05 | [Prompt caching](01_api_fundamentals/05_prompt_caching.ipynb) | Reuse a stable prompt prefix and track cached tokens. |
| 06 | [Reasoning and thinking tokens](01_api_fundamentals/06_reasoning_tokens.ipynb) | Control reasoning effort and replay reasoning across turns. |
| 07 | [Vision input](01_api_fundamentals/07_vision_input.ipynb) | Send images by URL or base64 and get structured analysis back. |
| 08 | [Long context](01_api_fundamentals/08_long_context.ipynb) | Pack repo-scale context into the context window. |
| 09 | [Error handling and retry](01_api_fundamentals/09_error_handling.ipynb) | Back off with jitter and skip retries on client errors. |
| 10 | [Search grounding](01_api_fundamentals/10_search_grounding.ipynb) | Ground responses in live web search results with inline citations. |

### [2. Agent patterns](02_agent_patterns/)

Build the loops that turn a model into an agent: planning, parallel work, and self-correction.

| # | Recipe | What it does |
|---|--------|--------------|
| 01 | [Basic agent loop](02_agent_patterns/01_agent_loop_basics/) | Wire up the core perceive-decide-act agent loop. |
| 02 | [Interleaved reasoning and tool use](02_agent_patterns/02_interleaved_reasoning/) | Interleave reasoning with tool calls in a single turn. |
| 03 | [Multi-turn context management](02_agent_patterns/03_managing_context/) | Manage growing context across a long agent run. |
| 04 | [Validated in-place edits](02_agent_patterns/04_validated_in_place_edits/) | Validated search-and-replace edits with a coding agent. |
| 05 | [Alert fatigue copilot](02_agent_patterns/05_alert_fatigue_copilot/) | Extract grounded patterns from a noisy alert feed, then probe → chat → self-assess with strict-JSON output. |

### [3. Use cases](03_use_cases/)

End-to-end patterns: multimodal perception, orchestration, and full applications.

| # | Recipe | What it does |
|---|--------|--------------|
| 01 | [Chart analysis](03_use_cases/01_chart-explainer/) | Read charts and extract structured data from images. |
| 02 | [Error screenshot fix](03_use_cases/02_screenshot_bugfix/) | Diagnose a bug from an error screenshot and fix it. |
| 03 | [Smart glasses with OpenClaw](03_use_cases/03_visionclaw/) | Hands-free look-and-ask on Ray-Ban Meta glasses. |
| 04 | [Generating slides](03_use_cases/04_doc_generation/) | Generate a slide deck from a prompt or source content. |
| 05 | [Browser-verified web design](03_use_cases/05_web_design/) | Build a website with a coding agent that checks its own work in a real browser. |
| 06 | [Iterative game dev](03_use_cases/06_iterative_game_dev/) | Build a browser game end-to-end with a coding agent, verified in a real browser. |
| 07 | [Sandboxed execution](03_use_cases/07_sandbox_execution/) | Execute model-generated code in a sandbox. |
| 08 | [Multi-agent product studio](03_use_cases/08_multi_agent_orchestration/) | Orchestrate a four-profile Hermes team (PM, backend, frontend, tech writer) that coordinates through a shared Kanban board. |
| 09 | [One-shot game dev](03_use_cases/09_one-shot-game_dev/) | Build a complete 3D browser game in a single pass — an AGENTS.md plus one structured prompt, no iteration loop. |
| 10 | [Perception grounding](03_use_cases/10_perception_grounding/) | Identify food items in a fridge photo, pin interactive health-score dots at their pixel locations, and generate a self-contained HTML overlay. |
| 11 | [GitHub repo agent](03_use_cases/11_github_repo_agent/) | Autonomous GitHub Actions bot — triage, PR review, AI-slop detection, and bug-fix PRs — built on OpenCode + Muse Spark. |
| 12 | [Computer use](03_use_cases/12_computer_use/) | Drive a Linux desktop from screenshots — the agent finds an app, opens it, and plays it, clicking through a Cua sandbox. |
| 13 | [macOS computer use](03_use_cases/13_macos_cua/) | Drive a real Mac from screenshots with `metacua`, a native computer-use agent (Swift + Python) that clicks, types, and works out a GUI app on its own. |

## License

See [LICENSE](LICENSE) for details.
