import { describe, it, expect, beforeAll, afterAll } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { Gateway } from "../src/gateway.js";
import type { ProxyConfig } from "../src/config.js";
import type { AccessLogEntry } from "../src/logger.js";

describe("e2e", () => {
  let backend1: http.Server;
  let backend2: http.Server;
  let port1: number;
  let port2: number;
  let gateway: Gateway;
  let gatewayServer: http.Server;
  let gatewayPort: number;
  const logs: AccessLogEntry[] = [];

  beforeAll(async () => {
    backend1 = http.createServer((_req, res) => { res.end("b1"); });
    await new Promise<void>(r => backend1.listen(0, r));
    port1 = (backend1.address() as AddressInfo).port;
    backend2 = http.createServer((_req, res) => { res.end("b2"); });
    await new Promise<void>(r => backend2.listen(0, r));
    port2 = (backend2.address() as AddressInfo).port;

    const cfg: ProxyConfig = {
      listenPort: 0,
      backends: [
        { id: "b1", tenantId: "t1", target: `http://localhost:${port1}` },
        { id: "b2", tenantId: "t1", target: `http://localhost:${port2}` },
      ],
      routes: [
        { id: "r1", tenantId: "t1", pathPrefix: "/", backends: ["b1", "b2"], strategy: "round-robin", rateLimit: { rps: 5, burst: 2 } },
      ],
      healthCheck: { enabled: false, intervalMs: 5000, timeoutMs: 1000, path: "/" },
      circuitBreaker: { failureThreshold: 5, cooldownMs: 30000, halfOpenMaxAttempts: 1 },
    };
    gateway = await Gateway.create(cfg, async (e) => { logs.push(e); });
    gatewayServer = gateway.createServer();
    await new Promise<void>(r => gatewayServer.listen(0, r));
    gatewayPort = (gatewayServer.address() as AddressInfo).port;
  });

  afterAll(() => {
    backend1.close();
    backend2.close();
    gatewayServer.close();
  });

  function get(path: string, tenantId = "t1") {
    return new Promise<{ status: number; body: string }>((resolve, reject) => {
      const req = http.get(`http://localhost:${gatewayPort}${path}`, { headers: { "x-tenant-id": tenantId } }, res => {
        let d = ""; res.on("data", c => d += c); res.on("end", () => resolve({ status: res.statusCode!, body: d }));
      });
      req.on("error", reject);
    });
  }

  it("proxies via router, round-robin, logs, metrics, rate limits", async () => {
    const r1 = await get("/");
    const r2 = await get("/");
    expect([r1.body, r2.body].sort()).toEqual(["b1", "b2"]);
    expect(logs.length).toBeGreaterThanOrEqual(2);
    expect(logs[0].tenantId).toBe("t1");
    const snap = await gateway.metrics.snapshot();
    expect(snap.requests).toBeGreaterThanOrEqual(2);

    const results = [];
    for (let i = 0; i < 5; i++) results.push(await get("/"));
    const statuses = results.map(r => r.status);
    expect(statuses.includes(429)).toBe(true);
  });

  it("tenant isolation", async () => {
    const r = await get("/", "t2");
    expect(r.status).toBe(404);
    expect(r.body).toBe("no route");
  });
});
