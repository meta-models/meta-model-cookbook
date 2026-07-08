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

## Issues and security

Use GitHub issues for public bugs; include clear, reproducible steps.

## License

By contributing, you agree that your contributions are licensed under the LICENSE file in the
root of this repository.
