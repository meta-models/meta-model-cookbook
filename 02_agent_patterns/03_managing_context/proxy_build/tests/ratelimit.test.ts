import { describe, it, expect } from "vitest";
import { RateLimiter, MultiRateLimiter } from "../src/ratelimit.js";

describe("ratelimit", () => {
  it("allows burst then throttles", async () => {
    const rl = new RateLimiter({ rps: 10, burst: 2 });
    expect(await rl.allow("ip", 0)).toBe(true);
    expect(await rl.allow("ip", 0)).toBe(true);
    expect(await rl.allow("ip", 0)).toBe(false);
    expect(await rl.allow("ip", 100)).toBe(true);
    expect(await rl.allow("ip", 100)).toBe(false);
  });

  it("refills over time", async () => {
    const rl = new RateLimiter({ rps: 1, burst: 1 });
    expect(await rl.allow("k", 0)).toBe(true);
    expect(await rl.allow("k", 500)).toBe(false);
    expect(await rl.allow("k", 1100)).toBe(true);
  });

  it("isolates keys", async () => {
    const rl = new RateLimiter({ rps: 1, burst: 1 });
    expect(await rl.allow("a", 0)).toBe(true);
    expect(await rl.allow("b", 0)).toBe(true);
    expect(await rl.allow("a", 0)).toBe(false);
  });

  it("multi limiter per route", async () => {
    const m = new MultiRateLimiter();
    await m.setRoute("t1", "r1", { rps: 1, burst: 1 });
    expect(await m.allow("t1", "r1", "ip", 0)).toBe(true);
    expect(await m.allow("t1", "r1", "ip", 0)).toBe(false);
    expect(await m.allow("t1", "r2", "ip", 0)).toBe(true);
    await m.setRoute("t1", "r1", undefined);
    expect(await m.allow("t1", "r1", "ip", 0)).toBe(true);
  });

  it("tenant isolation", async () => {
    const m = new MultiRateLimiter();
    await m.setRoute("t1", "r1", { rps: 1, burst: 1 });
    await m.setRoute("t2", "r1", { rps: 1, burst: 1 });
    expect(await m.allow("t1", "r1", "ip", 0)).toBe(true);
    expect(await m.allow("t1", "r1", "ip", 0)).toBe(false);
    expect(await m.allow("t2", "r1", "ip", 0)).toBe(true);
  });
});
