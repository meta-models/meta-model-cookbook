# Agent patterns

Maps to the **Agent patterns** section of the [Cookbook page](https://dev.meta.ai/docs/getting-started/cookbook#agent-patterns).
Recipes here build the loops that turn a model into an agent: planning, parallel
work, and self-correction.

## Recipes

| # | Recipe | What it does |
|---|--------|--------------|
| [01](01_agent_loop_basics/) | Basic agent loop | Wire up the core perceive-decide-act agent loop. |
| [02](02_interleaved_reasoning/) | Interleaved reasoning and tool use | Interleave reasoning with tool calls in a single turn. |
| [03](03_managing_context/) | Multi-turn context management | Manage growing context across a long agent run. |
| [04](04_validated_in_place_edits/) | Validated in-place edits | Validated search-and-replace in-place edits with a coding agent. |
| [05](05_alert_fatigue_copilot/) | Alert fatigue copilot | Extract grounded patterns from a noisy alert feed, then probe → chat → self-assess with strict-JSON output. |

Recipes 01–03 map to live website tiles (*Basic agent loop*, *Interleaved reasoning and
tool use*, *Multi-turn context management*). 04–05 are in-repo recipes with no live tile
(04 is from the retired `first-contact` section).
