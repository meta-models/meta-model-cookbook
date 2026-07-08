import { describe, it, expect } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { BackendPool } from "../src/pool.js";
import { RoundRobinBalancer } from "../src/balancer/index.js";
import { CircuitBreakerRegistry } from "../src/circuit.js";
import { ReverseProxy } from "../src/proxy.js";

function startBackend(status: number, body: string): Promise<{ port: number; close: () => void }> {
  return new Promise((resolve) => {
    const s = http.createServer((_req, res) => { res.writeHead(status); res.end(body); });
    s.listen(0, () => {
      resolve({ port: (s.address() as AddressInfo).port, close: () => s.close() });
    });
  });
}

describe("retries", () => {
  it("retries on 5xx and succeeds", async () => {
    let count = 0;
    const s = http.createServer((_req, res) => {
      count++;
      if (count === 1) { res.writeHead(502); res.end("bad"); }
      else { res.writeHead(200); res.end("ok"); }
    });
    await new Promise<void>(r => s.listen(0, r));
    const port = (s.address() as AddressInfo).port;

    const pool = new BackendPool();
    await pool.addBackend({ id: "b", tenantId: "t1", target: `http://localhost:${port}` });
    await pool.setHealth("b", "healthy");
    const circuit = new CircuitBreakerRegistry({ failureThreshold: 10, cooldownMs: 1000, halfOpenMaxAttempts: 1 });
    const proxy = new ReverseProxy({ pool, balancer: new RoundRobinBalancer(), circuit, backendIds: ["b"], retries: 1, retryIdempotentOnly: false });

    const proxyServer = http.createServer((req, res) => proxy.handle(req, res, "t1"));
    await new Promise<void>(r => proxyServer.listen(0, r));
    const pport = (proxyServer.address() as AddressInfo).port;

    const result = await new Promise<string>((resolve, reject) => {
      http.get(`http://localhost:${pport}/`, res => {
        let d = ""; res.on("data", c => d += c); res.on("end", () => resolve(d));
      }).on("error", reject);
    });

    expect(result).toBe("ok");
    expect(count).toBe(2);
    await new Promise<void>(r => proxyServer.close(() => r()));
    s.close();
  });

  it("does not retry non-idempotent by default", async () => {
    const b = await startBackend(502, "bad");
    const pool = new BackendPool();
    await pool.addBackend({ id: "x", tenantId: "t1", target: `http://localhost:${b.port}` });
    await pool.setHealth("x", "healthy");
    const circuit = new CircuitBreakerRegistry({ failureThreshold: 10, cooldownMs: 1000, halfOpenMaxAttempts: 1 });
    const proxy = new ReverseProxy({ pool, balancer: new RoundRobinBalancer(), circuit, backendIds: ["x"], retries: 2 });

    const ps = http.createServer((req, res) => proxy.handle(req, res, "t1"));
    await new Promise<void>(r => ps.listen(0, r));
    const pport = (ps.address() as AddressInfo).port;

    const status = await new Promise<number>((resolve, reject) => {
      const req = http.request(`http://localhost:${pport}/`, { method: "POST" }, res => {
        res.resume(); res.on("end", () => resolve(res.statusCode!));
      });
      req.on("error", reject);
      req.end("data");
    });
    expect(status).toBe(502);
    await new Promise<void>(r => ps.close(() => r()));
    b.close();
  });

  it("skips circuit-open backends during retry", async () => {
    const good = await startBackend(200, "good");
    const pool = new BackendPool();
    await pool.addBackend({ id: "bad", tenantId: "t1", target: "http://localhost:1" });
    await pool.addBackend({ id: "good", tenantId: "t1", target: `http://localhost:${good.port}` });
    await pool.setHealth("bad", "healthy");
    await pool.setHealth("good", "healthy");
    const circuit = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 60000, halfOpenMaxAttempts: 1 });
    await circuit.recordFailure("t1", "bad", Date.now());
    const proxy = new ReverseProxy({ pool, balancer: new RoundRobinBalancer(), circuit, backendIds: ["bad", "good"], retries: 1 });

    const ps = http.createServer((req, res) => proxy.handle(req, res, "t1"));
    await new Promise<void>(r => ps.listen(0, r));
    const pport = (ps.address() as AddressInfo).port;

    const body = await new Promise<string>((resolve, reject) => {
      http.get(`http://localhost:${pport}/`, res => {
        let d = ""; res.on("data", c => d += c); res.on("end", () => resolve(d));
      }).on("error", reject);
    });
    expect(body).toBe("good");
    await new Promise<void>(r => ps.close(() => r()));
    good.close();
  });
});
