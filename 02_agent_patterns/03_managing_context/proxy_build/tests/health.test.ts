import { describe, it, expect, beforeAll, afterAll } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { BackendPool } from "../src/pool.js";
import { HealthChecker } from "../src/health.js";

describe("health checker", () => {
  let serverOk: http.Server;
  let serverFail: http.Server;
  let portOk: number;
  let portFail: number;

  beforeAll(async () => {
    serverOk = http.createServer((_req, res) => { res.writeHead(200); res.end("ok"); });
    await new Promise<void>(r => serverOk.listen(0, r));
    portOk = (serverOk.address() as AddressInfo).port;

    serverFail = http.createServer((_req, res) => { res.writeHead(500); res.end("fail"); });
    await new Promise<void>(r => serverFail.listen(0, r));
    portFail = (serverFail.address() as AddressInfo).port;
  });

  afterAll(() => {
    serverOk.close();
    serverFail.close();
  });

  it("marks healthy/unhealthy via active check", async () => {
    const pool = new BackendPool();
    await pool.addBackend({ id: "ok", tenantId: "t1", target: `http://localhost:${portOk}` });
    await pool.addBackend({ id: "bad", tenantId: "t1", target: `http://localhost:${portFail}` });
    const hc = new HealthChecker(pool, { enabled: true, intervalMs: 1000, timeoutMs: 200, path: "/" });
    const ok = await hc.checkOne("t1", "ok");
    const bad = await hc.checkOne("t1", "bad");
    expect(ok).toBe(true);
    expect(bad).toBe(false);
    expect((await pool.get("ok"))?.health).toBe("healthy");
    expect((await pool.get("bad"))?.health).toBe("unhealthy");
  });

  it("passive health marks unhealthy after threshold", async () => {
    const pool = new BackendPool();
    await pool.addBackend({ id: "a", tenantId: "t1", target: "http://x" });
    await pool.setHealth("a", "healthy");
    expect(await pool.recordPassiveFailure("a", 2)).toBe(false);
    expect((await pool.get("a"))?.health).toBe("healthy");
    expect(await pool.recordPassiveFailure("a", 2)).toBe(true);
    expect((await pool.get("a"))?.health).toBe("unhealthy");
  });

  it("passive success resets failures but not health", async () => {
    const pool = new BackendPool();
    await pool.addBackend({ id: "a", tenantId: "t1", target: "http://x" });
    await pool.setHealth("a", "unhealthy");
    await pool.recordFailure("a");
    await pool.recordPassiveSuccess("a");
    expect((await pool.get("a"))?.consecutiveFailures).toBe(0);
    expect((await pool.get("a"))?.health).toBe("unhealthy");
  });
});
