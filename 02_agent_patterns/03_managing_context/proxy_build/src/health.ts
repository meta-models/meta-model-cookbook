import * as http from "node:http";
import * as https from "node:https";
import type { BackendPool } from "./pool.js";
import type { HealthCheckConfig } from "./config.js";

export class HealthChecker {
  private timer?: NodeJS.Timeout;
  private running = false;
  private abortController?: AbortController;

  constructor(private pool: BackendPool, private cfg: HealthCheckConfig) {}

  start(): void {
    if (this.running || !this.cfg.enabled) return;
    this.running = true;
    this.abortController = new AbortController();
    const tick = () => {
      if (!this.running) return;
      this.checkAll(this.abortController?.signal).catch(() => {});
      this.timer = setTimeout(tick, this.cfg.intervalMs);
    };
    tick();
  }

  stop(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.abortController?.abort();
  }

  async checkAll(signal?: AbortSignal): Promise<void> {
    const backends = await this.pool.listBackends(signal);
    await Promise.all(backends.map(b => this.checkOne(b.tenantId, b.id, signal)));
  }

  async checkOne(tenantId: string, id: string, signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    const backend = await this.pool.getBackend(id, tenantId, signal);
    if (!backend) return false;
    const url = new URL(this.cfg.path, backend.target);
    const isHttps = url.protocol === "https:";

    const ok = await new Promise<boolean>((resolve) => {
      if (signal?.aborted) return resolve(false);
      const client = isHttps ? https : http;
      const req = client.request(
        {
          hostname: url.hostname,
          port: url.port || (isHttps ? 443 : 80),
          path: url.pathname + url.search,
          method: "GET",
          signal,
        },
        (res) => {
          res.resume();
          resolve(res.statusCode !== undefined && res.statusCode < 400);
        }
      );
      req.on("timeout", () => { req.destroy(); resolve(false); });
      req.on("error", () => resolve(false));
      const timeout = setTimeout(() => { req.destroy(); resolve(false); }, this.cfg.timeoutMs);
      req.on("close", () => clearTimeout(timeout));
      req.end();
      signal?.addEventListener("abort", () => { req.destroy(); resolve(false); }, { once: true });
    });

    signal?.throwIfAborted();
    await this.pool.setHealth(id, ok ? "healthy" : "unhealthy", signal);
    if (ok) await this.pool.recordSuccess(id, signal);
    else await this.pool.recordFailure(id, signal);
    return ok;
  }
}
