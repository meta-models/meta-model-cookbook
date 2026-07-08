# HTTP Reverse Proxy + Load Balancer — Working Memory

## Goal
Build a production-grade HTTP reverse proxy / load balancer in TypeScript using only Node.js built-ins (+ vitest). Features: config validation, backend pool, streaming reverse proxy, multiple LB strategies (RR, least-connections, weighted, consistent-hash), active/passive health checks, per-backend circuit breaker, retries, host/path routing, per-route rate limiting, admin API with JWT+RBAC, metrics, structured access logging, e2e tests with real backends.

## Key Decisions
- Node built-in `http`/`https` only, no Express.
- Vitest for tests.
- Config: JSON load with manual validation (no external zod).
- BackendPool: in-memory, add/remove/list, health state.
- Proxy: stream req/res, preserve headers, hop-by-hop stripping.
- LB strategies pluggable; selector consults circuit breaker + health.
- CircuitBreaker: CLOSED/OPEN/HALF_OPEN, failure threshold, cooldown.
- Health: active TCP/HTTP probes + passive failure counting.
- Retries: configurable count, only idempotent methods by default, respects CB.
- Router: host + path prefix matching, longest-prefix wins.
- RateLimit: token bucket per route/IP, in-memory.
- Admin API: HTTP JSON, JWT HS256 (Node crypto), RBAC roles: admin, operator, viewer.
- Metrics: in-memory counters, /metrics JSON.
- Logging: JSON lines to stdout.
- E2E: spin real http servers as backends in tests.

## Task Graph
1. [completed] Bootstrap: remove Express, init STATE.md, create project scaffold, config module w/ validation + tests
2. [completed] BackendPool: add/remove/list + health state + tests
3. [completed] Load balancer strategies: RR, least-connections, weighted, consistent-hash + tests
4. [completed] Circuit breaker per-backend + tests
5. [completed] Core reverse proxy (streaming) + backend selection integration + tests w/ real backend
6. [completed] Active + passive health checks + tests
7. [completed] Retries integrated with CB/health + tests
8. [completed] Host/path router + tests
9. [completed] Per-route rate limiting + tests
10. [completed] Admin API w/ JWT + RBAC (manage backends/routes) + tests
11. [completed] Metrics + structured access logging + tests
12. [completed] End-to-end tests (real backends, full stack) + docs polish

## File Map (evolving)
- `src/config.ts` – Config load/validate (Task 1)
- `src/pool.ts` – BackendPool (Task 2)
- `src/balancer/*` – LB strategies (Task 3)
- `src/circuit.ts` – Circuit breaker (Task 4)
- `src/proxy.ts` – Reverse proxy core (Task 5)
- `src/health.ts` – Health checks (Task 6)
- `src/router.ts` – Host/path router (Task 8)
- `src/ratelimit.ts` – Rate limiting (Task 9)
- `src/admin.ts` – Admin API + JWT/RBAC (Task 10)
- `src/metrics.ts` – Metrics (Task 11)
- `src/logger.ts` – Structured logging (Task 11)
- `src/server.ts` – Main entry
- `tests/*` – Vitest suites mirroring src

## Current Step
Hierarchical pools + fully async/cancellable refactor complete – 51 tests green.

Key components delivered (v2):
- config.ts – async validation, hierarchical pools, cycle detection, AbortSignal
- pool.ts – async BackendPool with BackendNode/PoolNode, hierarchical resolution, health propagation, all methods async + cancellable
- balancer/* – async select() with signal, pool-aware, BalancerFactory
- circuit.ts – async CircuitBreakerRegistry with signal
- proxy.ts – fully async streaming reverse proxy, AbortSignal throughout, hierarchical pool resolution, cancellable I/O
- health.ts – async cancellable health checker, leaf-only probes, health propagates up pool tree
- router.ts – async match() with signal
- ratelimit.ts – async token bucket, signal support
- metrics.ts / logger.ts – async record/log with signal
- admin.ts + admin_auth.ts – async JWT/RBAC, pool CRUD endpoints (/pools), node listing
- gateway.ts – async Gateway.create(), per-pool balancers, full async pipeline
- 51 tests passing, e2e with real backends, hierarchical pools validated

## Open Questions
None
