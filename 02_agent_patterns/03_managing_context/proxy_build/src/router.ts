import type { RouteConfig } from "./config.js";

export interface MatchInput {
  host?: string;
  path: string;
}

export class Router {
  private routes: RouteConfig[];

  constructor(routes: RouteConfig[]) {
    this.routes = [...routes];
    this.sortRoutes();
  }

  private sortRoutes() {
    this.routes.sort((a, b) => {
      const ap = a.pathPrefix?.length ?? 0;
      const bp = b.pathPrefix?.length ?? 0;
      return bp - ap;
    });
  }

  async match(input: MatchInput, tenantId: string, signal?: AbortSignal): Promise<RouteConfig | null> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    const host = input.host ? input.host.split(":")[0].toLowerCase() : undefined;
    for (const r of this.routes) {
      signal?.throwIfAborted();
      if (r.tenantId !== tenantId) continue;
      if (r.host) {
        const rh = r.host.toLowerCase();
        if (!host || host !== rh) continue;
      }
      if (r.pathPrefix) {
        if (!input.path.startsWith(r.pathPrefix)) continue;
      }
      return r;
    }
    return null;
  }

  async getRoutes(signal?: AbortSignal): Promise<RouteConfig[]>;
  async getRoutes(tenantId: string, signal?: AbortSignal): Promise<RouteConfig[]>;
  async getRoutes(tenantIdOrSignal?: string | AbortSignal, signal?: AbortSignal): Promise<RouteConfig[]> {
    let tenantId: string | undefined;
    if (typeof tenantIdOrSignal === "string") {
      tenantId = tenantIdOrSignal;
    } else {
      signal = tenantIdOrSignal;
    }
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    return tenantId ? this.routes.filter(r => r.tenantId === tenantId) : this.routes;
  }

  async upsert(route: RouteConfig, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    this.routes = this.routes.filter(r => !(r.id === route.id && r.tenantId === route.tenantId));
    this.routes.push(route);
    this.sortRoutes();
  }

  async remove(id: string, tenantId?: string, signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    const before = this.routes.length;
    this.routes = this.routes.filter(r => tenantId ? !(r.id === id && r.tenantId === tenantId) : r.id !== id);
    return this.routes.length !== before;
  }
}
