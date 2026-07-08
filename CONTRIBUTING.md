# Contributing to the Meta Model API cookbook

Thanks for your interest in improving the cookbook. This repo is a curated set of
**self-contained, copy-paste recipes** for building on and with the Meta Model API. Every recipe
should prove one capability, run against the live API, and give a reader something to build
on. This guide explains how to add or change one.

## Before you start

- **Sign the Meta CLA.** A Contributor License Agreement is required before we can accept any
  pull request. You only need to do this once to contribute to any Meta open-source project.
  See [code.facebook.com/cla](https://code.facebook.com/cla).
- **Open an issue first for new recipes.** A quick issue describing the recipe (the capability
  it proves and which section it belongs in) lets us confirm scope before you invest time.
  Typo fixes, doc corrections, and small clarifications can go straight to a PR.

## Repo layout

The cookbook mirrors the three sections of the Meta Model API cookbook website. Pick the
section your recipe belongs to:

| Section | Directory | Focus |
|---------|-----------|-------|
| API fundamentals | [`01_api_fundamentals/`](01_api_fundamentals/) | Prove one API primitive works (chat, streaming, tools, vision, …). |
| Agent patterns | [`02_agent_patterns/`](02_agent_patterns/) | The loops that turn a model into an agent (planning, self-correction). |
| Use cases | [`03_use_cases/`](03_use_cases/) | End-to-end applications and multimodal patterns. |

## Canonical configuration

Every recipe uses **exactly** this setup. Copy it verbatim — do not vary the base URL, model
id, or key variable.

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
> Never commit an API key. Read it from the `MODEL_API_KEY` environment variable (see
> [`.env.example`](.env.example)); `.env` is git-ignored. Show token **usage**
> (`response.usage`), never dollar costs.

## Adding a recipe

Recipes come in two shapes; match whichever the section already uses.

**Notebook recipes** (used in `01_api_fundamentals/`): a single `NN_short_name.ipynb` file.
Follow the setup cell, helpers, voice, and structure of
[`01_api_fundamentals/01_chat_completions.ipynb`](01_api_fundamentals/01_chat_completions.ipynb),
the pilot every other notebook mirrors.

**Directory recipes** (used in `02_agent_patterns/` and `03_use_cases/`): a numbered folder
`NN_short_name/` containing:

- `README.md` — the recipe itself. Open with a title and a summary table (`Section`,
  `Time to complete`, `Model`, `Harness`/`Prerequisites` where relevant); see
  [`03_use_cases/06_iterative_game_dev/README.md`](03_use_cases/06_iterative_game_dev/README.md) for the format.
- Any supporting code, `assets/`, `screenshots/`, or `tests/` the recipe needs.

Conventions for either shape:

- **Number sequentially** using the next `NN` in the section (`08_…` if `07_…` is the last).
- Use a lowercase, `snake_case` (or `kebab-case`, matching neighbors) short name.
- Keep it self-contained and copy-paste runnable — no dependencies on other recipes at runtime.
- Store images under the recipe's own `assets/` or `screenshots/` folder. Do **not** hotlink
  external image hosts.

## Update the recipe tables

Every recipe appears in two tables. Add a row to both, keeping columns aligned:

1. The root [`README.md`](README.md) recipe table for the section.
2. The section's own `README.md` table (e.g. [`03_use_cases/README.md`](03_use_cases/README.md)).

If your section's README has a note about which recipes map to live website tiles, update it
so the counts stay accurate.

## Running and linting recipes

The tooling lives in the repo's `pyproject.toml` (`openai`, `papermill`, `notebook`,
`ipykernel`), installed with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
```

**Run a notebook recipe headless** (verifies every cell against the live API — a clean run
exits 0 with no error outputs):

```bash
MODEL_API_KEY="LLM|...|..." uv run papermill \
  01_api_fundamentals/01_chat_completions.ipynb /tmp/out.ipynb
```

**Open a recipe interactively:**

```bash
uv run jupyter notebook --no-browser --port 8888
```

**Lint and format** (this tree uses ruff, not black):

```bash
uv tool run ruff check .
uv tool run ruff format --check .
```

## Pull request checklist

Before you open a PR, confirm:

- [ ] You have signed the [Meta CLA](https://code.facebook.com/cla).
- [ ] The recipe runs clean against the live API (notebook recipes: `papermill` exits 0).
- [ ] `ruff check` and `ruff format --check` pass.
- [ ] No secrets, API keys, or `.env` files are committed.
- [ ] Both recipe tables (root and section README) are updated.
- [ ] Images are stored in-repo, not hotlinked from external hosts.

Fork the repo, branch from `main`, and open your PR against `main` with a short description of
what the recipe shows or proves.

## Issues and security

Use GitHub issues for public bugs; include clear, reproducible steps. **Do not** file security
vulnerabilities as public issues — report them through
[Meta's Bug Bounty program](https://www.facebook.com/whitehat).

## License

By contributing, you agree that your contributions are licensed under the LICENSE file in the
root of this repository.
