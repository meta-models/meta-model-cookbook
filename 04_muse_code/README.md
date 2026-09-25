# Muse Code

Recipes for building with [Muse Code](https://dev.meta.ai/docs/cookbook#building-with-muse-code) when you need sessions you can audit, safety that fails closed, and an agent team you can steer. Each recipe walks a task end to end and finishes with a proof point you can replay.

## Recipes

| # | Recipe | What it does |
|---|--------|--------------|
| [01](01_append_only_audit_log/) | Append-only audit log and crash-safe resume | Export the append-only session log and walk the exact sequence of actions and approvals as replayable evidence, then kill the harness mid-task and resume where it stopped with no duplicate side effects. |
| [02](02_deterministic_replay/) | Deterministic Replay in CI | Turn recorded Muse Code events into a focused golden fixture and replay its model-context projection as a merge-blocking check. |
| [03](03_staged_approvals/) | Staged approvals for compound shell commands | Decompose a compound shell command into stages, auto-clear the safe ones, and hold the dangerous or unparseable ones for review. Trust is scoped per action and per workspace, and fails closed. |
| [04](04_contained_execution/) | Contained execution you can prove | Run shell commands inside an OS-level sandbox that live-probes its own enforcement and refuses to run when containment isn't enforcing. |
| [05](05_immutable_guardrails/) | The agent can't rewrite its own rules | Ask the agent to edit the guardrail file it runs under; the write stops for human review with no standing grant on offer, and a shell write to the same path fails read-only at the sandbox. |
| [06](06_subagent_fanout/) | Subagent fanout across isolated worktrees | Distribute one job across parallel subagents, each in its own git worktree, steered or stopped from a single control point. |
| [07](07_goal_tracking/) | Goal tracking with a pinned objective | Pin the objective once with `/goal`; the harness carries it across turns and audits the work against the acceptance checks before the goal can close. |
| [08](08_bundled_skills/) | Bundled skills: plan, pressure-test, and build | Drive the built-in `/plan`, `/grilling`, `/grill-with-docs`, and `/taste` skills end to end: plan a change, pressure-test it, record the decisions, and build UI that doesn't look AI-made. |
| [09](09_loop_and_cron/) | Loop and cron: scheduled agent work | Schedule recurring or one-time agent work in natural language, then view, change, or cancel it from the same chat surface. |
| [10](10_side_chats/) | Multi-turn side chats | Branch a multi-turn side conversation off a busy main thread with `/side` (or its alias `/btw`), isolated from the main transcript. |
| [11](11_mcp_security_tooling/) | Security research over MCP | Wire Burp Suite, headless Ghidra and LLDB into Muse Code over MCP, then point it at a deliberately vulnerable web server and a real CVE in a stripped binary and watch how it works. |
