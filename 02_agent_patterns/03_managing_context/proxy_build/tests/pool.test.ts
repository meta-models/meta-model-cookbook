import { describe, it, expect } from "vitest";
import { BackendPool } from "../src/pool.js";

describe("BackendPool", () => {
  it("adds, lists, gets, removes", async () => {
    const p = new BackendPool();
    await p.addBackend({ id: "a", tenantId: "t1", target: "http://localhost:3001" });
    expect((await p.list()).length).toBe(1);
    expect((await p.getBackend("a", "t1"))?.target).toBe("http://localhost:3001");
    expect(await p.remove("a", "t1")).toBe(true);
    expect((await p.list()).length).toBe(0);
  });

  it("rejects duplicate", async () => {
    const p = new BackendPool([{ id: "a", tenantId: "t1", target: "http://x" }]);
    await expect(p.addBackend({ id: "a", tenantId: "t1", target: "http://y" })).rejects.toThrow();
  });

  it("tracks health and failures", async () => {
    const p = new BackendPool([{ id: "a", tenantId: "t1", target: "http://x" }]);
    await p.setHealth("a", "healthy");
    expect((await p.get("a"))?.health).toBe("healthy");
    await p.recordFailure("a");
    expect((await p.get("a"))?.consecutiveFailures).toBe(1);
    await p.recordSuccess("a");
    expect((await p.get("a"))?.consecutiveFailures).toBe(0);
  });

  it("tracks connections", async () => {
    const p = new BackendPool([{ id: "a", tenantId: "t1", target: "http://x" }]);
    await p.incConnections("a");
    await p.incConnections("a");
    expect((await p.get("a"))?.activeConnections).toBe(2);
    await p.decConnections("a");
    expect((await p.get("a"))?.activeConnections).toBe(1);
  });

  it("getHealthy filters", async () => {
    const p = new BackendPool([
      { id: "a", tenantId: "t1", target: "http://a" },
      { id: "b", tenantId: "t1", target: "http://b" },
    ]);
    await p.setHealth("a", "healthy");
    await p.setHealth("b", "unhealthy");
    const healthy = await p.getHealthy("t1");
    expect(healthy.map(x => x.id)).toEqual(["a"]);
  });

  it("updates backend", async () => {
    const p = new BackendPool([{ id: "a", tenantId: "t1", target: "http://a", weight: 1 }]);
    await p.updateBackend({ id: "a", tenantId: "t1", target: "http://b", weight: 5 });
    const b = (await p.get("a"))!;
    expect((b as any).target).toBe("http://b");
    expect(b.weight).toBe(5);
  });

  it("supports hierarchical pools", async () => {
    const p = new BackendPool([{ id: "a", tenantId: "t1", target: "http://a" }, { id: "b", tenantId: "t1", target: "http://b" }]);
    await p.addPool({ id: "p1", tenantId: "t1", members: ["a", "b"], strategy: "round-robin" });
    const leaves = await p.resolveLeafBackends(["p1"], "t1");
    expect(leaves.map(x => x.id).sort()).toEqual(["a", "b"]);
    await p.setHealth("a", "healthy");
    const pool = await p.get("p1");
    expect(pool?.health).toBe("healthy");
  });

  it("cancels via AbortSignal", async () => {
    const p = new BackendPool();
    const ac = new AbortController();
    ac.abort();
    await expect(p.addBackend({ id: "x", tenantId: "t1", target: "http://x" }, ac.signal)).rejects.toThrow();
  });

  it("tenant isolation", async () => {
    const p = new BackendPool([
      { id: "a", tenantId: "t1", target: "http://a" },
      { id: "b", tenantId: "t2", target: "http://b" },
    ]);
    expect((await p.list("t1")).map(x => x.id)).toEqual(["a"]);
    expect((await p.list("t2")).map(x => x.id)).toEqual(["b"]);
    expect(await p.get("a", "t2")).toBeUndefined();
    expect(await p.getBackend("a", "t2")).toBeUndefined();
    expect(await p.remove("a", "t2")).toBe(false);
    await p.addPool({ id: "p1", tenantId: "t1", members: ["a"], strategy: "round-robin" });
    await expect(p.addPool({ id: "p2", tenantId: "t2", members: ["a"], strategy: "round-robin" })).rejects.toThrow(/cross-tenant/);
  });
});
