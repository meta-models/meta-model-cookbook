import * as http from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { BackendPool } from "./pool.js";
import type { Router } from "./router.js";
import type { AdminConfig, BackendConfig, RouteConfig, PoolConfig } from "./config.js";
import { verifyJWT, verifyPassword, signJWT, roleAllows, type Role } from "./admin_auth.js";
import type { MultiRateLimiter } from "./ratelimit.js";

export interface AdminContext {
  pool: BackendPool;
  router: Router;
  rateLimiter?: MultiRateLimiter;
  config: AdminConfig;
}

function json(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

function readBody(req: IncomingMessage, signal?: AbortSignal): Promise<any> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    let data = "";
    const onAbort = () => reject(signal?.reason);
    signal?.addEventListener("abort", onAbort, { once: true });
    req.on("data", c => data += c);
    req.on("end", () => {
      signal?.removeEventListener("abort", onAbort);
      if (!data) return resolve({});
      try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
    });
    req.on("error", (e) => { signal?.removeEventListener("abort", onAbort); reject(e); });
  });
}

async function getAuthRole(req: IncomingMessage, secret: string, signal?: AbortSignal): Promise<{ role: Role; sub: string; tenantId: string } | null> {
  signal?.throwIfAborted();
  const auth = req.headers["authorization"];
  if (!auth || !auth.startsWith("Bearer ")) return null;
  const payload = await verifyJWT(auth.slice(7), secret, signal);
  return payload ? { role: payload.role, sub: payload.sub, tenantId: payload.tenantId } : null;
}

export function createAdminHandler(ctx: AdminContext, signal?: AbortSignal) {
  return async (req: IncomingMessage, res: ServerResponse) => {
    signal?.throwIfAborted();
    const url = new URL(req.url || "/", `http://${req.headers.host}`);
    const path = url.pathname;

    if (path === "/login" && req.method === "POST") {
      try {
        const body = await readBody(req, signal);
        const user = ctx.config.users.find(u => u.username === body.username);
        if (!user || !(await verifyPassword(body.password || "", user.passwordHash, signal))) {
          return json(res, 401, { error: "invalid credentials" });
        }
        const exp = Math.floor(Date.now() / 1000) + 3600;
        const token = await signJWT({ sub: user.username, role: user.role, exp }, ctx.config.jwtSecret, signal);
        return json(res, 200, { token });
      } catch {
        return json(res, 400, { error: "bad request" });
      }
    }

    const auth = await getAuthRole(req, ctx.config.jwtSecret, signal);
    if (!auth) return json(res, 401, { error: "unauthorized" });

    if (path === "/backends" && req.method === "GET") {
      if (!roleAllows(auth.role, "viewer")) return json(res, 403, { error: "forbidden" });
      return json(res, 200, await ctx.pool.listBackends(auth.tenantId, signal));
    }

    if (path === "/backends" && req.method === "POST") {
      if (!roleAllows(auth.role, "operator")) return json(res, 403, { error: "forbidden" });
      try {
        const body = await readBody(req, signal) as BackendConfig;
        if (body.tenantId !== auth.tenantId) return json(res, 403, { error: "tenant mismatch" });
        const b = await ctx.pool.addBackend(body, signal);
        return json(res, 201, b);
      } catch (e) {
        return json(res, 400, { error: (e as Error).message });
      }
    }

    const backendMatch = path.match(/^\/backends\/([^/]+)$/);
    if (backendMatch) {
      const id = decodeURIComponent(backendMatch[1]);
      if (req.method === "GET") {
        if (!roleAllows(auth.role, "viewer")) return json(res, 403, { error: "forbidden" });
        const node = await ctx.pool.getBackend(id, auth.tenantId, signal);
        return node ? json(res, 200, node) : json(res, 404, { error: "not found" });
      }
      if (req.method === "DELETE") {
        if (!roleAllows(auth.role, "operator")) return json(res, 403, { error: "forbidden" });
        const ok = await ctx.pool.remove(id, auth.tenantId, signal);
        return json(res, ok ? 204 : 404, {});
      }
      if (req.method === "PUT") {
        if (!roleAllows(auth.role, "operator")) return json(res, 403, { error: "forbidden" });
        try {
          const body = await readBody(req, signal) as BackendConfig;
          if (body.id !== id) return json(res, 400, { error: "id mismatch" });
          if (body.tenantId !== auth.tenantId) return json(res, 403, { error: "tenant mismatch" });
          const b = await ctx.pool.updateBackend(body, signal);
          return json(res, 200, b);
        } catch (e) {
          return json(res, 400, { error: (e as Error).message });
        }
      }
    }

    if (path === "/pools" && req.method === "GET") {
      if (!roleAllows(auth.role, "viewer")) return json(res, 403, { error: "forbidden" });
      return json(res, 200, await ctx.pool.listPools(auth.tenantId, signal));
    }

    if (path === "/pools" && req.method === "POST") {
      if (!roleAllows(auth.role, "operator")) return json(res, 403, { error: "forbidden" });
      try {
        const body = await readBody(req, signal) as PoolConfig;
        if (body.tenantId !== auth.tenantId) return json(res, 403, { error: "tenant mismatch" });
        const p = await ctx.pool.addPool(body, signal);
        return json(res, 201, p);
      } catch (e) {
        return json(res, 400, { error: (e as Error).message });
      }
    }

    const poolMatch = path.match(/^\/pools\/([^/]+)$/);
    if (poolMatch) {
      const id = decodeURIComponent(poolMatch[1]);
      if (req.method === "GET") {
        if (!roleAllows(auth.role, "viewer")) return json(res, 403, { error: "forbidden" });
        const node = await ctx.pool.get(id, auth.tenantId, signal);
        return node && node.kind === "pool" ? json(res, 200, node) : json(res, 404, { error: "not found" });
      }
      if (req.method === "DELETE") {
        if (!roleAllows(auth.role, "operator")) return json(res, 403, { error: "forbidden" });
        const ok = await ctx.pool.remove(id, auth.tenantId, signal);
        return json(res, ok ? 204 : 404, {});
      }
      if (req.method === "PUT") {
        if (!roleAllows(auth.role, "operator")) return json(res, 403, { error: "forbidden" });
        try {
          const body = await readBody(req, signal) as PoolConfig;
          if (body.id !== id) return json(res, 400, { error: "id mismatch" });
          if (body.tenantId !== auth.tenantId) return json(res, 403, { error: "tenant mismatch" });
          const p = await ctx.pool.updatePool(body, signal);
          return json(res, 200, p);
        } catch (e) {
          return json(res, 400, { error: (e as Error).message });
        }
      }
    }

    if (path === "/nodes" && req.method === "GET") {
      if (!roleAllows(auth.role, "viewer")) return json(res, 403, { error: "forbidden" });
      return json(res, 200, await ctx.pool.list(auth.tenantId, signal));
    }

    if (path === "/routes" && req.method === "GET") {
      if (!roleAllows(auth.role, "viewer")) return json(res, 403, { error: "forbidden" });
      return json(res, 200, await ctx.router.getRoutes(auth.tenantId, signal));
    }

    if (path === "/routes" && req.method === "POST") {
      if (!roleAllows(auth.role, "admin")) return json(res, 403, { error: "forbidden" });
      try {
        const body = await readBody(req, signal) as RouteConfig;
        if (body.tenantId !== auth.tenantId) return json(res, 403, { error: "tenant mismatch" });
        for (const bid of body.backends) {
          if (!await ctx.pool.get(bid, auth.tenantId, signal)) return json(res, 400, { error: `unknown backend ${bid}` });
        }
        await ctx.router.upsert(body, signal);
        await ctx.rateLimiter?.setRoute(body.tenantId, body.id, body.rateLimit, signal);
        return json(res, 201, body);
      } catch (e) {
        return json(res, 400, { error: (e as Error).message });
      }
    }

    const routeMatch = path.match(/^\/routes\/([^/]+)$/);
    if (routeMatch && req.method === "DELETE") {
      if (!roleAllows(auth.role, "admin")) return json(res, 403, { error: "forbidden" });
      const id = decodeURIComponent(routeMatch[1]);
      const ok = await ctx.router.remove(id, auth.tenantId, signal);
      await ctx.rateLimiter?.setRoute(auth.tenantId, id, undefined, signal);
      return json(res, ok ? 204 : 404, {});
    }

    json(res, 404, { error: "not found" });
  };
}

export function startAdminServer(ctx: AdminContext, signal?: AbortSignal): http.Server {
  const handler = createAdminHandler(ctx, signal);
  const server = http.createServer(handler);
  server.listen(ctx.config.listenPort);
  return server;
}
