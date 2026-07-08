import { readFileSync } from "node:fs";

export type LBStrategy = "round-robin" | "least-connections" | "weighted" | "consistent-hash";

export interface TenantContext {
  tenantId: string;
}

export interface BackendConfig {
  id: string;
  tenantId: string;
  target: string;
  weight?: number;
}

export interface PoolConfig {
  id: string;
  tenantId: string;
  members: string[];
  strategy?: LBStrategy;
  weight?: number;
}

export interface RouteConfig {
  id: string;
  tenantId: string;
  host?: string;
  pathPrefix?: string;
  backends: string[];
  strategy: LBStrategy;
  rateLimit?: { rps: number; burst: number };
  retries?: number;
}

export interface HealthCheckConfig {
  enabled: boolean;
  intervalMs: number;
  timeoutMs: number;
  path: string;
}

export interface CircuitBreakerConfig {
  failureThreshold: number;
  cooldownMs: number;
  halfOpenMaxAttempts: number;
}

export interface AdminConfig {
  listenPort: number;
  jwtSecret: string;
  users: Array<{ username: string; passwordHash: string; role: "admin" | "operator" | "viewer" }>;
}

export interface ProxyConfig {
  listenPort: number;
  backends: BackendConfig[];
  pools?: PoolConfig[];
  routes: RouteConfig[];
  healthCheck: HealthCheckConfig;
  circuitBreaker: CircuitBreakerConfig;
  admin?: AdminConfig;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function assertString(v: unknown, name: string): string {
  if (typeof v !== "string" || v.length === 0) throw new ConfigError(`${name} must be non-empty string`);
  return v;
}

function assertNumber(v: unknown, name: string, min = 0): number {
  if (typeof v !== "number" || !Number.isFinite(v) || v < min) throw new ConfigError(`${name} must be number >= ${min}`);
  return v;
}

function assertPort(v: unknown, name: string): number {
  const n = assertNumber(v, name, 1);
  if (n > 65535 || !Number.isInteger(n)) throw new ConfigError(`${name} must be integer 1-65535`);
  return n;
}

export async function validateProxyConfig(input: unknown, signal?: AbortSignal): Promise<ProxyConfig> {
  signal?.throwIfAborted();
  if (!isObject(input)) throw new ConfigError("config must be object");
  const listenPort = assertPort(input.listenPort, "listenPort");

  if (!Array.isArray(input.backends) || input.backends.length === 0)
    throw new ConfigError("backends must be non-empty array");
  const backends: BackendConfig[] = [];
  const nodeIds = new Map<string, string>(); // id -> tenantId
  for (const b of input.backends) {
    signal?.throwIfAborted();
    await new Promise(resolve => setImmediate(resolve));
    if (!isObject(b)) throw new ConfigError("backend must be object");
    const id = assertString(b.id, "backend.id");
    if (nodeIds.has(id)) throw new ConfigError(`duplicate node id: ${id}`);
    const tenantId = assertString((b as any).tenantId, "backend.tenantId");
    nodeIds.set(id, tenantId);
    const target = assertString((b as any).target, "backend.target");
    try {
      const u = new URL(target);
      if (u.protocol !== "http:" && u.protocol !== "https:") throw new Error();
    } catch {
      throw new ConfigError(`backend.target invalid URL: ${target}`);
    }
    let weight: number | undefined;
    if ((b as any).weight !== undefined) {
      weight = assertNumber((b as any).weight, "backend.weight", 1);
    }
    backends.push({ id, tenantId, target, weight });
  }

  const pools: PoolConfig[] = [];
  if (input.pools !== undefined) {
    if (!Array.isArray(input.pools)) throw new ConfigError("pools must be array");
    for (const p of input.pools) {
      signal?.throwIfAborted();
      await new Promise(resolve => setImmediate(resolve));
      if (!isObject(p)) throw new ConfigError("pool must be object");
      const id = assertString(p.id, "pool.id");
      if (nodeIds.has(id)) throw new ConfigError(`duplicate node id: ${id}`);
      const tenantId = assertString((p as any).tenantId, "pool.tenantId");
      nodeIds.set(id, tenantId);
      if (!Array.isArray(p.members) || p.members.length === 0)
        throw new ConfigError(`pool ${id} members must be non-empty array`);
      const members = (p.members as unknown[]).map((m, i) => {
        if (typeof m !== "string") throw new ConfigError(`pool ${id} member ${i} must be string`);
        return m;
      });
      let strategy: LBStrategy | undefined;
      if (p.strategy !== undefined) {
        if (!["round-robin","least-connections","weighted","consistent-hash"].includes(p.strategy as string))
          throw new ConfigError(`pool ${id} invalid strategy`);
        strategy = p.strategy as LBStrategy;
      }
      let weight: number | undefined;
      if (p.weight !== undefined) weight = assertNumber(p.weight, `pool ${id} weight`, 1);
      pools.push({ id, tenantId, members, strategy, weight });
    }
    for (const pool of pools) {
      for (const m of pool.members) {
        const memberTenant = nodeIds.get(m);
        if (!memberTenant) throw new ConfigError(`pool ${pool.id} references unknown member ${m}`);
        if (memberTenant !== pool.tenantId) throw new ConfigError(`pool ${pool.id} member ${m} cross-tenant violation`);
      }
    }
    const graph = new Map(pools.map(p => [p.id, p.members.filter(m => pools.some(pp => pp.id === m))]));
    const visited = new Set<string>();
    const stack = new Set<string>();
    const dfs = (id: string): boolean => {
      if (stack.has(id)) return true;
      if (visited.has(id)) return false;
      visited.add(id); stack.add(id);
      for (const n of graph.get(id) ?? []) if (dfs(n)) return true;
      stack.delete(id); return false;
    };
    for (const p of pools) if (dfs(p.id)) throw new ConfigError(`pool ${p.id} introduces cycle`);
  }

  if (!Array.isArray(input.routes) || input.routes.length === 0)
    throw new ConfigError("routes must be non-empty array");
  const routes: RouteConfig[] = [];
  const routeIds = new Set<string>();
  for (const r of input.routes) {
    signal?.throwIfAborted();
    await new Promise(resolve => setImmediate(resolve));
    if (!isObject(r)) throw new ConfigError("route must be object");
    const id = assertString(r.id, "route.id");
    if (routeIds.has(id)) throw new ConfigError(`duplicate route id: ${id}`);
    routeIds.add(id);
    const tenantId = assertString((r as any).tenantId, "route.tenantId");
    const host = r.host !== undefined ? assertString(r.host, "route.host") : undefined;
    const pathPrefix = r.pathPrefix !== undefined ? assertString(r.pathPrefix, "route.pathPrefix") : undefined;
    if (!host && !pathPrefix) throw new ConfigError(`route ${id} must have host or pathPrefix`);
    if (!Array.isArray(r.backends) || r.backends.length === 0)
      throw new ConfigError(`route ${id} backends must be non-empty array`);
    for (const bid of r.backends) {
      if (typeof bid !== "string") throw new ConfigError(`route ${id} backend must be string`);
      const nodeTenant = nodeIds.get(bid);
      if (!nodeTenant) throw new ConfigError(`route ${id} references unknown backend/pool ${bid}`);
      if (nodeTenant !== tenantId) throw new ConfigError(`route ${id} backend ${bid} cross-tenant violation`);
    }
    const strategy = r.strategy;
    if (!["round-robin","least-connections","weighted","consistent-hash"].includes(strategy as string))
      throw new ConfigError(`route ${id} invalid strategy`);
    let rateLimit: { rps: number; burst: number } | undefined;
    if (r.rateLimit !== undefined) {
      if (!isObject(r.rateLimit)) throw new ConfigError(`route ${id} rateLimit must be object`);
      rateLimit = {
        rps: assertNumber(r.rateLimit.rps, `route ${id} rateLimit.rps`, 1),
        burst: assertNumber(r.rateLimit.burst, `route ${id} rateLimit.burst`, 1),
      };
    }
    let retries: number | undefined;
    if (r.retries !== undefined) retries = assertNumber(r.retries, `route ${id} retries`, 0);
    routes.push({
      id,
      tenantId,
      host,
      pathPrefix,
      backends: r.backends as string[],
      strategy: strategy as LBStrategy,
      rateLimit,
      retries,
    });
  }

  signal?.throwIfAborted();
  if (!isObject(input.healthCheck)) throw new ConfigError("healthCheck must be object");
  const healthCheck: HealthCheckConfig = {
    enabled: Boolean(input.healthCheck.enabled),
    intervalMs: assertNumber(input.healthCheck.intervalMs, "healthCheck.intervalMs", 100),
    timeoutMs: assertNumber(input.healthCheck.timeoutMs, "healthCheck.timeoutMs", 10),
    path: assertString(input.healthCheck.path, "healthCheck.path"),
  };
  if (healthCheck.timeoutMs >= healthCheck.intervalMs)
    throw new ConfigError("healthCheck.timeoutMs must be < intervalMs");

  if (!isObject(input.circuitBreaker)) throw new ConfigError("circuitBreaker must be object");
  const circuitBreaker: CircuitBreakerConfig = {
    failureThreshold: assertNumber(input.circuitBreaker.failureThreshold, "circuitBreaker.failureThreshold", 1),
    cooldownMs: assertNumber(input.circuitBreaker.cooldownMs, "circuitBreaker.cooldownMs", 10),
    halfOpenMaxAttempts: assertNumber(input.circuitBreaker.halfOpenMaxAttempts, "circuitBreaker.halfOpenMaxAttempts", 1),
  };

  let admin: AdminConfig | undefined;
  if (input.admin !== undefined) {
    signal?.throwIfAborted();
    if (!isObject(input.admin)) throw new ConfigError("admin must be object");
    const listenPort = assertPort(input.admin.listenPort, "admin.listenPort");
    const jwtSecret = assertString(input.admin.jwtSecret, "admin.jwtSecret");
    if (jwtSecret.length < 16) throw new ConfigError("admin.jwtSecret must be >=16 chars");
    if (!Array.isArray(input.admin.users)) throw new ConfigError("admin.users must be array");
    const users: AdminConfig["users"] = [];
    for (const u of input.admin.users) {
      signal?.throwIfAborted();
      if (!isObject(u)) throw new ConfigError("admin.user must be object");
      const username = assertString(u.username, "admin.user.username");
      const passwordHash = assertString(u.passwordHash, "admin.user.passwordHash");
      const role = u.role;
      if (role !== "admin" && role !== "operator" && role !== "viewer")
        throw new ConfigError("admin.user.role invalid");
      users.push({ username, passwordHash, role });
    }
    admin = { listenPort, jwtSecret, users };
  }

  return { listenPort, backends, pools: pools.length ? pools : undefined, routes, healthCheck, circuitBreaker, admin };
}

export async function loadConfig(path: string, signal?: AbortSignal): Promise<ProxyConfig> {
  const { readFile } = await import("node:fs/promises");
  const raw = await readFile(path, "utf8");
  signal?.throwIfAborted();
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    throw new ConfigError(`invalid JSON: ${(e as Error).message}`);
  }
  return validateProxyConfig(parsed, signal);
}
