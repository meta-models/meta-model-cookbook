import * as http from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import { BackendPool } from "./pool.js";
import { Router } from "./router.js";
import { CircuitBreakerRegistry } from "./circuit.js";
import { RoundRobinBalancer, LeastConnectionsBalancer, WeightedBalancer, ConsistentHashBalancer } from "./balancer/index.js";
import { ReverseProxy } from "./proxy.js";
import { MultiRateLimiter } from "./ratelimit.js";
import { Metrics } from "./metrics.js";
import { jsonLogger, type Logger } from "./logger.js";
import type { ProxyConfig, RouteConfig } from "./config.js";

function makeBalancer(strategy: RouteConfig["strategy"]) {
  switch (strategy) {
    case "least-connections": return new LeastConnectionsBalancer();
    case "weighted": return new WeightedBalancer();
    case "consistent-hash": return new ConsistentHashBalancer();
    default: return new RoundRobinBalancer();
  }
}

export class Gateway {
  pool: BackendPool;
  router: Router;
  circuit: CircuitBreakerRegistry;
  rateLimiter: MultiRateLimiter;
  metrics: Metrics;
  logger: Logger;
  private balancers = new Map<string, ReturnType<typeof makeBalancer>>();

  private constructor(private cfg: ProxyConfig, logger?: Logger) {
    this.pool = new BackendPool();
    this.router = new Router(cfg.routes);
    this.circuit = new CircuitBreakerRegistry(cfg.circuitBreaker);
    this.rateLimiter = new MultiRateLimiter();
    this.metrics = new Metrics();
    this.logger = logger ?? jsonLogger;
  }

  static async create(cfg: ProxyConfig, logger?: Logger, signal?: AbortSignal): Promise<Gateway> {
    const gw = new Gateway(cfg, logger);
    for (const b of cfg.backends) {
      await gw.pool.addBackend(b, signal);
      await gw.pool.setHealth(b.id, "healthy", signal);
    }
    if (cfg.pools) {
      for (const p of cfg.pools) {
        await gw.pool.addPool(p, signal);
        await gw.pool.setHealth(p.id, "healthy", signal);
      }
    }
    for (const r of cfg.routes) {
      await gw.rateLimiter.setRoute(r.tenantId, r.id, r.rateLimit, signal);
      gw.balancers.set(`${r.tenantId}:${r.id}`, makeBalancer(r.strategy));
    }
    return gw;
  }

  async handle(req: IncomingMessage, res: ServerResponse, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    const start = Date.now();
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
    const tenantId = (req.headers["x-tenant-id"] as string) || "default";
    const route = await this.router.match({ host: req.headers.host, path: url.pathname }, tenantId, signal);
    if (!route) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("no route");
      await this.metrics.record(tenantId, undefined, 404, Date.now() - start, signal);
      await this.logger({ ts: new Date().toISOString(), tenantId, method: req.method, path: url.pathname, status: 404, latencyMs: Date.now() - start, clientIp: req.socket.remoteAddress ?? undefined }, signal);
      return;
    }
    const clientIp = req.socket.remoteAddress || "unknown";
    if (!await this.rateLimiter.allow(tenantId, route.id, clientIp, Date.now(), signal)) {
      res.writeHead(429, { "content-type": "text/plain" });
      res.end("rate limit");
      await this.metrics.record(tenantId, route.id, 429, Date.now() - start, signal);
      await this.logger({ ts: new Date().toISOString(), tenantId, method: req.method, path: url.pathname, status: 429, latencyMs: Date.now() - start, route: route.id, clientIp }, signal);
      return;
    }

    const balancerKey = `${tenantId}:${route.id}`;
    let balancer = this.balancers.get(balancerKey);
    if (!balancer) {
      balancer = makeBalancer(route.strategy);
      this.balancers.set(balancerKey, balancer);
    }
    const proxy = new ReverseProxy({
      pool: this.pool,
      balancer,
      circuit: this.circuit,
      backendIds: route.backends,
      retries: route.retries ?? 0,
      hashKey: route.strategy === "consistent-hash" ? (r) => r.headers["x-client-id"] as string || clientIp : undefined,
    });

    let statusCode = 502;
    const origWriteHead = res.writeHead.bind(res);
    res.writeHead = ((status: number, ...args: any[]) => {
      statusCode = status;
      return origWriteHead(status, ...args as any);
    }) as any;

    res.on("finish", () => {
      const latency = Date.now() - start;
      this.metrics.record(tenantId, route.id, statusCode, latency, signal).catch(()=>{});
      this.logger({ ts: new Date().toISOString(), tenantId, method: req.method, path: url.pathname, status: statusCode, latencyMs: latency, route: route.id, clientIp }, signal).catch(()=>{});
    });

    await proxy.handle(req, res, tenantId, signal);
  }

  getBalancerForPool(poolId: string, strategy: RouteConfig["strategy"]): ReturnType<typeof makeBalancer> {
    const key = `pool:${poolId}`;
    let b = this.balancers.get(key);
    if (!b) {
      b = makeBalancer(strategy);
      this.balancers.set(key, b);
    }
    return b;
  }

  createServer(signal?: AbortSignal): http.Server {
    return http.createServer((req, res) => { this.handle(req, res, signal).catch(() => { if (!res.headersSent) { res.writeHead(500); res.end(); } }); });
  }
}
