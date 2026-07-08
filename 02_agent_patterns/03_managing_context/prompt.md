# The Prompt We Used

This recipe is grounded in one real OpenCode run against `muse-spark-1.1`. This file is the exact prompting we used, so the run is reproducible and it is clear what we asked the model to do.

The shape matters: the model is given the **initial spec first** and builds the whole thing. Each **requirement change is then injected one at a time, only after the previous one is done and green** — never revealed in advance. That is deliberate: if the model could see the changes up front it would pre-design for them, and there would be no real refactoring. Surfacing each change late forces it to revisit and rework decisions it already made.

## Initial prompt (given first)

```text
You are the engineer on a new HTTP reverse proxy + load balancer. Build it in TypeScript using only Node.js built-in modules plus the existing vitest tooling. Work one task at a time and keep the full test suite green throughout.

Discipline (apply on every task):
- Maintain and actively leverage STATE.md as your working memory: record the goal, key decisions, a task graph with status, the files each task touches, the current step, and open questions. Update it after every task, consult it before starting each task, and use its file map to find affected code when something changes.
- Before editing a file you last read more than a couple of turns ago, re-read it in full from disk.
- Production-grade only: real algorithms, full edge cases, validation, error handling. No stubs, placeholders, or TODOs.
- When a change ripples, update every affected module and its tests. Never leave the codebase inconsistent or the suite red. Run the full suite after each task.

Requirements:
- a config module with validation
- a backend pool (add, remove, list)
- a core reverse proxy that streams a request to a selected backend
- selection strategies: round-robin, least-connections, weighted, consistent-hash
- active and passive health checks
- a per-backend circuit breaker that the proxy and selectors consult
- retries integrated with the circuit breaker and health state
- host and path routing
- per-route rate limiting
- an admin API with JWT and RBAC to manage backends and routes at runtime
- metrics and structured access logging
- end-to-end tests that stand up real backend servers

Build the whole thing task by task, then stop and wait.
```

## Requirement changes (each injected one at a time, only after the previous is done and green)

```text
1. New requirement from product: backends are now hierarchical - a pool can contain sub-pools as well as backends. Update the system so selection, health checks, routing, rate limiting, and the admin API all work correctly with nested pools, and keep the full suite green.

2. New requirement: all backend I/O and health checks must become fully async and cancellable. Convert every synchronous path and every caller, update all tests, and keep the full suite green.

3. New requirement: the proxy must be multi-tenant. A tenant context has to flow through routing, pool selection, rate limiting, metrics, and logging. Make every module and test tenant-aware, and keep the full suite green.
```
