import { describe, it, expect, beforeAll, afterAll } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { BackendPool } from "../src/pool.js";
import { RoundRobinBalancer } from "../src/balancer/index.js";
import { CircuitBreakerRegistry } from "../src/circuit.js";
import { ReverseProxy } from "../src/proxy.js";

function startBackend(handler: http.RequestListener): Promise<{ server: http.Server; port: number }> {
  return new Promise(resolve => {
    const server = http.createServer(handler);
    server.listen(0, () => {
      const port = (server.address() as AddressInfo).port;
      resolve({ server, port });
    });
  });
}

describe("reverse proxy", () => {
  let backend1: http.Server;
  let backend2: http.Server;
  let port1: number;
  let port2: number;

  beforeAll(async () => {
    const b1 = await startBackend((_req, res) => {
      res.writeHead(200, { "content-type": "text/plain", "x-backend": "1" });
      res.end("backend1");
    });
    backend1 = b1.server; port1 = b1.port;
    const b2 = await startBackend((req, res) => {
      let body = "";
      req.on("data", chunk => { body += chunk; });
      req.on("end", () => {
        res.writeHead(200, { "content-type": "text/plain", "x-backend": "2" });
        res.end(`backend2:${body}`);
      });
    });
    backend2 = b2.server; port2 = b2.port;
  });

  afterAll(() => {
    backend1.close();
    backend2.close();
  });

  it("proxies GET and streams", async () => {
    const pool = new BackendPool();
    await pool.addBackend({ id: "b1", tenantId: "t1", target: `http://localhost:${port1}` });
    await pool.addBackend({ id: "b2", tenantId: "t1", target: `http://localhost:${port2}` });
    await pool.setHealth("b1", "healthy");
    await pool.setHealth("b2", "healthy");
    const circuit = new CircuitBreakerRegistry({ failureThreshold: 5, cooldownMs: 1000, halfOpenMaxAttempts: 1 });
    const proxy = new ReverseProxy({ pool, balancer: new RoundRobinBalancer(), circuit, backendIds: ["b1", "b2"] });

    const proxyServer = http.createServer((req, res) => { proxy.handle(req, res, "t1"); });
    await new Promise<void>(r => proxyServer.listen(0, r));
    const proxyPort = (proxyServer.address() as AddressInfo).port;

    const get = (path: string) => new Promise<{ status: number; body: string; headers: http.IncomingHttpHeaders }>((resolve, reject) => {
      http.get(`http://localhost:${proxyPort}${path}`, res => {
        let data = "";
        res.on("data", c => data += c);
        res.on("end", () => resolve({ status: res.statusCode!, body: data, headers: res.headers }));
      }).on("error", reject);
    });

    const r1 = await get("/foo?x=1");
    expect(r1.status).toBe(200);
    expect(r1.body).toBe("backend1");

    const post = await new Promise<{ status: number; body: string }>((resolve, reject) => {
      const req = http.request(`http://localhost:${proxyPort}/test`, { method: "POST" }, res => {
        let d = "";
        res.on("data", c => d += c);
        res.on("end", () => resolve({ status: res.statusCode!, body: d }));
      });
      req.on("error", reject);
      req.end("hello");
    });
    expect(post.body).toBe("backend2:hello");

    await new Promise<void>(r => proxyServer.close(() => r()));
  });

  it("skips unhealthy / circuit-open backends", async () => {
    const pool = new BackendPool();
    await pool.addBackend({ id: "b1", tenantId: "t1", target: `http://localhost:${port1}` });
    await pool.addBackend({ id: "b2", tenantId: "t1", target: `http://localhost:${port2}` });
    await pool.setHealth("b1", "unhealthy");
    await pool.setHealth("b2", "healthy");
    const circuit = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 60000, halfOpenMaxAttempts: 1 });
    await circuit.recordFailure("t1", "b2", Date.now());
    expect(await circuit.canRequest("t1", "b2")).toBe(false);

    const proxy = new ReverseProxy({ pool, balancer: new RoundRobinBalancer(), circuit, backendIds: ["b1", "b2"] });
    const proxyServer = http.createServer((req, res) => { proxy.handle(req, res, "t1"); });
    await new Promise<void>(r => proxyServer.listen(0, r));
    const proxyPort = (proxyServer.address() as AddressInfo).port;

    const result = await new Promise<{ status: number }>((resolve, reject) => {
      http.get(`http://localhost:${proxyPort}/`, res => {
        res.resume();
        res.on("end", () => resolve({ status: res.statusCode! }));
      }).on("error", reject);
    });
    expect(result.status).toBe(502);
    await new Promise<void>(r => proxyServer.close(() => r()));
  });
});
