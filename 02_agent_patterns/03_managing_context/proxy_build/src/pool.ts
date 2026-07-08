import type { BackendConfig, PoolConfig, LBStrategy } from "./config.js";

export type HealthStatus = "healthy" | "unhealthy" | "unknown";

export interface BackendNode {
  kind: "backend";
  id: string;
  tenantId: string;
  target: string;
  weight: number;
  health: HealthStatus;
  activeConnections: number;
  consecutiveFailures: number;
  lastCheckAt?: number;
}

export interface PoolNode {
  kind: "pool";
  id: string;
  tenantId: string;
  members: string[];
  strategy: LBStrategy;
  weight: number;
  health: HealthStatus;
  activeConnections: number;
  consecutiveFailures: number;
  lastCheckAt?: number;
}

export type Node = BackendNode | PoolNode;
export type Backend = BackendNode;

function delay(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const onAbort = () => { clearImmediate(im); reject(signal?.reason); };
    const im = setImmediate(() => { signal?.removeEventListener("abort", onAbort); resolve(); });
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export class BackendPool {
  private nodes = new Map<string, Node>();

  constructor(initialBackends: BackendConfig[] = [], initialPools: PoolConfig[] = []) {
    for (const b of initialBackends) this.addBackendSync(b);
    for (const p of initialPools) this.addPoolSync(p);
  }

  private addBackendSync(cfg: BackendConfig): BackendNode {
    if (this.nodes.has(cfg.id)) throw new Error(`node ${cfg.id} already exists`);
    const node: BackendNode = {
      kind: "backend",
      id: cfg.id,
      tenantId: cfg.tenantId,
      target: cfg.target,
      weight: cfg.weight ?? 1,
      health: "unknown",
      activeConnections: 0,
      consecutiveFailures: 0,
    };
    this.nodes.set(cfg.id, node);
    return node;
  }

  private addPoolSync(cfg: PoolConfig): PoolNode {
    if (this.nodes.has(cfg.id)) throw new Error(`node ${cfg.id} already exists`);
    const node: PoolNode = {
      kind: "pool",
      id: cfg.id,
      tenantId: cfg.tenantId,
      members: [...cfg.members],
      strategy: cfg.strategy ?? "round-robin",
      weight: cfg.weight ?? 1,
      health: "unknown",
      activeConnections: 0,
      consecutiveFailures: 0,
    };
    this.nodes.set(cfg.id, node);
    return node;
  }

  async addBackend(cfg: BackendConfig, signal?: AbortSignal): Promise<BackendNode> {
    signal?.throwIfAborted();
    await delay(signal);
    try {
      new URL(cfg.target);
    } catch {
      throw new Error(`invalid target URL: ${cfg.target}`);
    }
    return this.addBackendSync(cfg);
  }

  async addPool(cfg: PoolConfig, signal?: AbortSignal): Promise<PoolNode> {
    signal?.throwIfAborted();
    await delay(signal);
    for (const m of cfg.members) {
      const member = this.nodes.get(m);
      if (!member) throw new Error(`unknown member ${m}`);
      if (member.tenantId !== cfg.tenantId) throw new Error(`pool ${cfg.id} member ${m} cross-tenant violation`);
    }
    if (this.wouldCreateCycle(cfg.id, cfg.members)) throw new Error(`pool ${cfg.id} would create cycle`);
    return this.addPoolSync(cfg);
  }

  private wouldCreateCycle(id: string, members: string[]): boolean {
    const visit = (nodeId: string, seen: Set<string>): boolean => {
      if (nodeId === id) return true;
      if (seen.has(nodeId)) return false;
      seen.add(nodeId);
      const n = this.nodes.get(nodeId);
      if (n?.kind === "pool") {
        for (const m of n.members) if (visit(m, seen)) return true;
      }
      return false;
    };
    for (const m of members) if (visit(m, new Set())) return true;
    return false;
  }

  async remove(id: string, tenantId?: string, signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    await delay(signal);
    const node = this.nodes.get(id);
    if (node && tenantId && node.tenantId !== tenantId) return false;
    return this.nodes.delete(id);
  }

  async get(id: string, tenantId?: string, signal?: AbortSignal): Promise<Node | undefined> {
    signal?.throwIfAborted();
    await delay(signal);
    const node = this.nodes.get(id);
    if (node && tenantId && node.tenantId !== tenantId) return undefined;
    return node;
  }

  async getBackend(id: string, tenantId?: string, signal?: AbortSignal): Promise<BackendNode | undefined> {
    const n = await this.get(id, tenantId, signal);
    return n?.kind === "backend" ? n : undefined;
  }

  async list(signal?: AbortSignal): Promise<Node[]>;
  async list(tenantId: string, signal?: AbortSignal): Promise<Node[]>;
  async list(tenantIdOrSignal?: string | AbortSignal, signal?: AbortSignal): Promise<Node[]> {
    let tenantId: string | undefined;
    if (typeof tenantIdOrSignal === "string") {
      tenantId = tenantIdOrSignal;
    } else {
      signal = tenantIdOrSignal;
    }
    signal?.throwIfAborted();
    await delay(signal);
    const all = Array.from(this.nodes.values());
    return tenantId ? all.filter(n => n.tenantId === tenantId) : all;
  }

  async listBackends(signal?: AbortSignal): Promise<BackendNode[]>;
  async listBackends(tenantId: string, signal?: AbortSignal): Promise<BackendNode[]>;
  async listBackends(tenantIdOrSignal?: string | AbortSignal, signal?: AbortSignal): Promise<BackendNode[]> {
    let tenantId: string | undefined;
    if (typeof tenantIdOrSignal === "string") {
      tenantId = tenantIdOrSignal;
    } else {
      signal = tenantIdOrSignal;
    }
    const all = await this.list(tenantId!, signal);
    return all.filter((n): n is BackendNode => n.kind === "backend");
  }

  async listPools(signal?: AbortSignal): Promise<PoolNode[]>;
  async listPools(tenantId: string, signal?: AbortSignal): Promise<PoolNode[]>;
  async listPools(tenantIdOrSignal?: string | AbortSignal, signal?: AbortSignal): Promise<PoolNode[]> {
    let tenantId: string | undefined;
    if (typeof tenantIdOrSignal === "string") {
      tenantId = tenantIdOrSignal;
    } else {
      signal = tenantIdOrSignal;
    }
    const all = await this.list(tenantId!, signal);
    return all.filter((n): n is PoolNode => n.kind === "pool");
  }

  async setHealth(id: string, status: HealthStatus, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (!n) return;
    n.health = status;
    n.lastCheckAt = Date.now();
    if (status === "healthy") n.consecutiveFailures = 0;
    await this.propagateHealthUp(id, signal);
  }

  private async propagateHealthUp(changedId: string, signal?: AbortSignal): Promise<void> {
    for (const node of this.nodes.values()) {
      if (node.kind === "pool" && node.members.includes(changedId)) {
        signal?.throwIfAborted();
        const childHealths = await Promise.all(node.members.map(async m => {
          const c = this.nodes.get(m);
          return c?.health ?? "unknown";
        }));
        const newHealth: HealthStatus = childHealths.includes("healthy") ? "healthy"
          : childHealths.every(h => h === "unhealthy") ? "unhealthy" : "unknown";
        if (node.health !== newHealth) {
          node.health = newHealth;
          node.lastCheckAt = Date.now();
          await this.propagateHealthUp(node.id, signal);
        }
      }
    }
  }

  async recordFailure(id: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (!n) return;
    n.consecutiveFailures += 1;
  }

  async recordSuccess(id: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (!n) return;
    n.consecutiveFailures = 0;
  }

  async recordPassiveFailure(id: string, threshold: number, signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (!n) return false;
    n.consecutiveFailures += 1;
    if (n.consecutiveFailures >= threshold && n.health !== "unhealthy") {
      n.health = "unhealthy";
      n.lastCheckAt = Date.now();
      await this.propagateHealthUp(id, signal);
      return true;
    }
    return false;
  }

  async recordPassiveSuccess(id: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (!n) return;
    n.consecutiveFailures = 0;
  }

  async incConnections(id: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (n) n.activeConnections += 1;
  }

  async decConnections(id: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (n && n.activeConnections > 0) n.activeConnections -= 1;
  }

  async getHealthy(tenantId: string, ids?: string[], signal?: AbortSignal): Promise<Node[]> {
    signal?.throwIfAborted();
    await delay(signal);
    const all = ids
      ? (await Promise.all(ids.map(id => this.get(id, tenantId, signal)))).filter(Boolean) as Node[]
      : await this.list(tenantId, signal);
    return all.filter(b => b.health !== "unhealthy");
  }

  async updateBackend(cfg: BackendConfig, signal?: AbortSignal): Promise<BackendNode> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(cfg.id);
    if (!n || n.kind !== "backend") throw new Error(`backend ${cfg.id} not found`);
    if (n.tenantId !== cfg.tenantId) throw new Error(`backend ${cfg.id} cross-tenant violation`);
    n.target = cfg.target;
    if (cfg.weight !== undefined) n.weight = cfg.weight;
    return n;
  }

  async updatePool(cfg: PoolConfig, signal?: AbortSignal): Promise<PoolNode> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(cfg.id);
    if (!n || n.kind !== "pool") throw new Error(`pool ${cfg.id} not found`);
    if (n.tenantId !== cfg.tenantId) throw new Error(`pool ${cfg.id} cross-tenant violation`);
    for (const m of cfg.members) {
      const member = this.nodes.get(m);
      if (!member) throw new Error(`unknown member ${m}`);
      if (member.tenantId !== cfg.tenantId) throw new Error(`pool ${cfg.id} member ${m} cross-tenant violation`);
    }
    const oldMembers = n.members;
    n.members = [...cfg.members];
    if (this.wouldCreateCycle(cfg.id, cfg.members)) { n.members = oldMembers; throw new Error("cycle detected"); }
    if (cfg.strategy) n.strategy = cfg.strategy;
    if (cfg.weight !== undefined) n.weight = cfg.weight;
    return n;
  }

  async resolveLeafBackends(nodeIds: string[], tenantId: string, signal?: AbortSignal): Promise<BackendNode[]> {
    signal?.throwIfAborted();
    const result: BackendNode[] = [];
    const seen = new Set<string>();
    const walk = async (id: string): Promise<void> => {
      signal?.throwIfAborted();
      if (seen.has(id)) return;
      seen.add(id);
      const n = this.nodes.get(id);
      if (!n) return;
      if (n.tenantId !== tenantId) return;
      if (n.kind === "backend") { result.push(n); return; }
      for (const m of n.members) await walk(m);
    };
    for (const id of nodeIds) await walk(id);
    return result;
  }

  async getNodeWithStrategy(id: string, signal?: AbortSignal): Promise<{ node: Node; strategy?: LBStrategy }> {
    signal?.throwIfAborted();
    await delay(signal);
    const n = this.nodes.get(id);
    if (!n) throw new Error(`node ${id} not found`);
    return { node: n, strategy: n.kind === "pool" ? n.strategy : undefined };
  }
}
