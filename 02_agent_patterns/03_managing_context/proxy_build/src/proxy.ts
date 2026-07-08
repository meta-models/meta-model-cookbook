import * as http from "node:http";
import * as https from "node:https";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { BackendPool, Node, BackendNode } from "./pool.js";
import type { Balancer } from "./balancer/types.js";
import type { CircuitBreakerRegistry } from "./circuit.js";

const HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function filterHeaders(headers: http.IncomingHttpHeaders): http.OutgoingHttpHeaders {
  const out: http.OutgoingHttpHeaders = {};
  for (const [k, v] of Object.entries(headers)) {
    if (!k) continue;
    if (HOP_HEADERS.has(k.toLowerCase())) continue;
    out[k] = v;
  }
  return out;
}

export interface ProxyOptions {
  pool: BackendPool;
  balancer: Balancer;
  circuit: CircuitBreakerRegistry;
  backendIds: string[];
  hashKey?: (req: IncomingMessage) => string | undefined;
  passiveHealthThreshold?: number;
  retries?: number;
  retryIdempotentOnly?: boolean;
}

export class ReverseProxy {
  private passiveThreshold: number;
  private retries: number;
  private retryIdempotentOnly: boolean;
  constructor(private opts: ProxyOptions) {
    this.passiveThreshold = opts.passiveHealthThreshold ?? 3;
    this.retries = opts.retries ?? 0;
    this.retryIdempotentOnly = opts.retryIdempotentOnly ?? true;
  }

  async handle(req: IncomingMessage, res: ServerResponse, tenantId: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    const bodyChunks: Buffer[] = [];
    const canRetryBody = !this.retryIdempotentOnly || isIdempotent(req.method);
    let bodyCollected = false;

    if (this.retries > 0 && canRetryBody) {
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => reject(signal?.reason);
        signal?.addEventListener("abort", onAbort, { once: true });
        req.on("data", (c) => bodyChunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c)));
        req.on("end", () => { signal?.removeEventListener("abort", onAbort); bodyCollected = true; resolve(); });
        req.on("error", (e) => { signal?.removeEventListener("abort", onAbort); resolve(); });
      });
    }

    const attempt = async (attemptNum: number, tried: Set<string>): Promise<boolean> => {
      signal?.throwIfAborted();
      let nodes = await this.opts.pool.getHealthy(tenantId, this.opts.backendIds, signal);
      nodes = (await Promise.all(nodes.map(async n => {
        const ok = n.kind === "backend" ? await this.opts.circuit.canRequest(tenantId, n.id, Date.now(), signal) : true;
        return ok ? n : null;
      }))).filter(Boolean) as Node[];
      nodes = nodes.filter(b => !tried.has(b.id));
      if (nodes.length === 0) {
        nodes = await this.opts.pool.getHealthy(tenantId, this.opts.backendIds, signal);
        nodes = (await Promise.all(nodes.map(async n => {
          const ok = n.kind === "backend" ? await this.opts.circuit.canRequest(tenantId, n.id, Date.now(), signal) : true;
          return ok ? n : null;
        }))).filter(Boolean) as Node[];
      }
      if (nodes.length === 0) return false;
      const key = this.opts.hashKey?.(req);
      const selected = await this.opts.balancer.select(nodes, { tenantId, key, signal });
      if (!selected) return false;

      const backend = await this.resolveToLeaf(selected, tenantId, key, signal);
      if (!backend) return false;
      tried.add(backend.id);

      return new Promise<boolean>((resolve) => {
        signal?.throwIfAborted();
        const targetUrl = new URL(req.url || "/", backend.target);
        const isHttps = targetUrl.protocol === "https:";
        const client = isHttps ? https : http;

        const headers = filterHeaders(req.headers);
        headers["x-forwarded-for"] = req.socket.remoteAddress || "";
        headers["x-forwarded-proto"] = isHttps ? "https" : "http";
        headers["x-forwarded-host"] = req.headers.host || "";
        if (req.headers.host) headers["host"] = targetUrl.host;

        this.opts.pool.incConnections(backend.id, signal).catch(()=>{});
        this.opts.circuit.recordAttempt(tenantId, backend.id, signal).catch(()=>{});

        let completed = false;
        const finish = (success: boolean) => {
          if (completed) return;
          completed = true;
          this.opts.pool.decConnections(backend.id, signal).catch(()=>{});
          resolve(success);
        };

        const abortHandler = () => { proxyReq.destroy(new Error("aborted")); finish(false); };
        signal?.addEventListener("abort", abortHandler, { once: true });

        const proxyReq = client.request(
          {
            protocol: targetUrl.protocol,
            hostname: targetUrl.hostname,
            port: targetUrl.port || (isHttps ? 443 : 80),
            method: req.method,
            path: targetUrl.pathname + targetUrl.search,
            headers,
            signal,
          },
          (proxyRes) => {
            const status = proxyRes.statusCode || 502;
            const shouldRetry = status >= 500 && attemptNum < this.retries && canRetryBody;
            if (shouldRetry) {
              proxyRes.resume();
              this.opts.pool.decConnections(backend.id, signal).catch(()=>{});
              this.opts.circuit.recordFailure(tenantId, backend.id, Date.now(), signal).catch(()=>{});
              this.opts.pool.recordPassiveFailure(backend.id, this.passiveThreshold, signal).catch(()=>{});
              signal?.removeEventListener("abort", abortHandler);
              resolve(false);
              return;
            }
            const filtered = filterHeaders(proxyRes.headers);
            if (!res.headersSent) res.writeHead(status, filtered);
            proxyRes.pipe(res);
            proxyRes.on("end", () => {
              signal?.removeEventListener("abort", abortHandler);
              if (status < 500) {
                this.opts.circuit.recordSuccess(tenantId, backend.id, signal).catch(()=>{});
                this.opts.pool.recordPassiveSuccess(backend.id, signal).catch(()=>{});
              } else {
                this.opts.circuit.recordFailure(tenantId, backend.id, Date.now(), signal).catch(()=>{});
                this.opts.pool.recordPassiveFailure(backend.id, this.passiveThreshold, signal).catch(()=>{});
              }
              finish(true);
            });
          }
        );

        proxyReq.on("timeout", () => proxyReq.destroy(new Error("timeout")));
        proxyReq.on("error", () => {
          signal?.removeEventListener("abort", abortHandler);
          this.opts.pool.decConnections(backend.id, signal).catch(()=>{});
          this.opts.circuit.recordFailure(tenantId, backend.id, Date.now(), signal).catch(()=>{});
          this.opts.pool.recordPassiveFailure(backend.id, this.passiveThreshold, signal).catch(()=>{});
          finish(false);
        });

        if (bodyCollected) {
          for (const chunk of bodyChunks) proxyReq.write(chunk);
          proxyReq.end();
        } else {
          req.pipe(proxyReq);
          req.on("aborted", () => proxyReq.destroy());
        }
      });
    };

    const tried = new Set<string>();
    for (let i = 0; i <= this.retries; i++) {
      signal?.throwIfAborted();
      const ok = await attempt(i, tried);
      if (ok) return;
      if (i < this.retries && canRetryBody) await new Promise(r => setTimeout(r, 10 * (i + 1)));
    }
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain" });
      res.end("bad gateway");
    }
  }

  private async resolveToLeaf(node: Node, tenantId: string, key: string | undefined, signal?: AbortSignal): Promise<BackendNode | null> {
    signal?.throwIfAborted();
    if (node.kind === "backend") {
      const can = await this.opts.circuit.canRequest(tenantId, node.id, Date.now(), signal);
      return can ? node : null;
    }
    const poolNode = node;
    const members = await this.opts.pool.getHealthy(tenantId, poolNode.members, signal);
    const healthyMembers = (await Promise.all(members.map(async m => {
      if (m.kind === "backend") {
        const ok = await this.opts.circuit.canRequest(tenantId, m.id, Date.now(), signal);
        return ok ? m : null;
      }
      return m;
    }))).filter(Boolean) as Node[];
    if (healthyMembers.length === 0) return null;
    const { BalancerFactory } = await import("./balancer/factory.js");
    const balancer = BalancerFactory.create(poolNode.strategy);
    const selected = await balancer.select(healthyMembers, { tenantId, key, signal });
    if (!selected) return null;
    return this.resolveToLeaf(selected, tenantId, key, signal);
  }
}

function isIdempotent(method?: string): boolean {
  return method === "GET" || method === "HEAD" || method === "OPTIONS" || method === "PUT" || method === "DELETE";
}
