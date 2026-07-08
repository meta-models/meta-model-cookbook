import { describe, it, expect } from "vitest";
import { CircuitBreakerRegistry } from "../src/circuit.js";

describe("circuit breaker", () => {
  it("opens after threshold", async () => {
    const cb = new CircuitBreakerRegistry({ failureThreshold: 2, cooldownMs: 1000, halfOpenMaxAttempts: 1 });
    expect(await cb.canRequest("t1", "a")).toBe(true);
    await cb.recordFailure("t1", "a", 0);
    expect(await cb.getState("t1", "a")).toBe("closed");
    await cb.recordFailure("t1", "a", 10);
    expect(await cb.getState("t1", "a")).toBe("open");
    expect(await cb.canRequest("t1", "a", 20)).toBe(false);
  });

  it("transitions half_open after cooldown", async () => {
    const cb = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 100, halfOpenMaxAttempts: 2 });
    await cb.recordFailure("t1", "b", 0);
    expect(await cb.canRequest("t1", "b", 50)).toBe(false);
    expect(await cb.canRequest("t1", "b", 150)).toBe(true);
    expect(await cb.getState("t1", "b")).toBe("half_open");
  });

  it("closes on success from half_open", async () => {
    const cb = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 50, halfOpenMaxAttempts: 1 });
    await cb.recordFailure("t1", "c", 0);
    expect(await cb.canRequest("t1", "c", 100)).toBe(true);
    await cb.recordAttempt("t1", "c");
    await cb.recordSuccess("t1", "c");
    expect(await cb.getState("t1", "c")).toBe("closed");
    expect(await cb.canRequest("t1", "c", 110)).toBe(true);
  });

  it("reopens on failure in half_open", async () => {
    const cb = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 10, halfOpenMaxAttempts: 1 });
    await cb.recordFailure("t1", "d", 0);
    expect(await cb.canRequest("t1", "d", 20)).toBe(true);
    await cb.recordFailure("t1", "d", 25);
    expect(await cb.getState("t1", "d")).toBe("open");
    expect(await cb.canRequest("t1", "d", 30)).toBe(false);
  });

  it("aborts via signal", async () => {
    const cb = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 10, halfOpenMaxAttempts: 1 });
    const ac = new AbortController(); ac.abort();
    await expect(cb.canRequest("t1", "x", Date.now(), ac.signal)).rejects.toThrow();
  });

  it("tenant isolation", async () => {
    const cb = new CircuitBreakerRegistry({ failureThreshold: 1, cooldownMs: 1000, halfOpenMaxAttempts: 1 });
    await cb.recordFailure("t1", "a", 0);
    expect(await cb.getState("t1", "a")).toBe("open");
    expect(await cb.getState("t2", "a")).toBe("closed");
    expect(await cb.canRequest("t2", "a")).toBe(true);
  });
});
