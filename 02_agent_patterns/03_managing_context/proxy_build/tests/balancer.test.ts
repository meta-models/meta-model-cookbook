import { describe, it, expect } from "vitest";
import { RoundRobinBalancer, LeastConnectionsBalancer, WeightedBalancer, ConsistentHashBalancer } from "../src/balancer/index.js";
import type { BackendNode } from "../src/pool.js";

function mk(id: string, weight = 1, conns = 0): BackendNode {
  return { kind: "backend", id, tenantId: "t1", target: "http://x", weight, health: "healthy", activeConnections: conns, consecutiveFailures: 0 };
}

describe("balancers", () => {
  it("round robin cycles", async () => {
    const rr = new RoundRobinBalancer();
    const bs = [mk("a"), mk("b"), mk("c")];
    expect((await rr.select(bs))?.id).toBe("a");
    expect((await rr.select(bs))?.id).toBe("b");
    expect((await rr.select(bs))?.id).toBe("c");
    expect((await rr.select(bs))?.id).toBe("a");
  });

  it("least connections picks lowest", async () => {
    const lc = new LeastConnectionsBalancer();
    const bs = [mk("a", 1, 5), mk("b", 1, 2), mk("c", 1, 9)];
    expect((await lc.select(bs))?.id).toBe("b");
  });

  it("weighted respects weights", async () => {
    const w = new WeightedBalancer();
    const bs = [mk("a", 1), mk("b", 3)];
    const counts: Record<string, number> = { a: 0, b: 0 };
    for (let i = 0; i < 400; i++) {
      const sel = (await w.select(bs, { key: `k${i}` }))!;
      counts[sel.id] += 1;
    }
    expect(counts.b).toBeGreaterThan(counts.a * 2);
  });

  it("consistent hash stable", async () => {
    const ch = new ConsistentHashBalancer();
    const bs = [mk("a"), mk("b"), mk("c")];
    const first = (await ch.select(bs, { key: "user-123" }))?.id;
    for (let i = 0; i < 10; i++) {
      expect((await ch.select(bs, { key: "user-123" }))?.id).toBe(first);
    }
  });

  it("returns null on empty", async () => {
    const rr = new RoundRobinBalancer();
    expect(await rr.select([])).toBeNull();
  });

  it("aborts via signal", async () => {
    const rr = new RoundRobinBalancer();
    const ac = new AbortController();
    ac.abort();
    await expect(rr.select([mk("a")], { signal: ac.signal })).rejects.toThrow();
  });
});
