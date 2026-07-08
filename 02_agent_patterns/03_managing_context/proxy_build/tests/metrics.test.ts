import { describe, it, expect } from "vitest";
import { Metrics } from "../src/metrics.js";
import { createTestLogger } from "../src/logger.js";

describe("metrics/logging", () => {
  it("records metrics", async () => {
    const m = new Metrics();
    await m.record("t1", "r1", 200, 10);
    await m.record("t1", "r1", 502, 5);
    const s = await m.snapshot();
    expect(s.requests).toBe(2);
    expect(s.errors).toBe(1);
    expect(s.byStatus["200"]).toBe(1);
    expect(s.byRoute["t1:r1"]).toBe(2);
    expect(s.avgLatencyMs).toBeCloseTo(7.5);
    expect(s.byTenant["t1"].requests).toBe(2);
  });

  it("logger captures entries", async () => {
    const out: any[] = [];
    const log = createTestLogger(out);
    await log({ ts: "x", tenantId: "t1", status: 200, latencyMs: 1 });
    expect(out.length).toBe(1);
  });

  it("tenant isolation", async () => {
    const m = new Metrics();
    await m.record("t1", "r1", 200, 10);
    await m.record("t2", "r1", 200, 20);
    const s = await m.snapshot();
    expect(s.byTenant["t1"].requests).toBe(1);
    expect(s.byTenant["t2"].requests).toBe(1);
    expect(s.byTenant["t1"].avgLatencyMs).toBe(10);
    expect(s.byTenant["t2"].avgLatencyMs).toBe(20);
  });
});
