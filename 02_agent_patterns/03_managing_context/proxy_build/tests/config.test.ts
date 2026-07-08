import { describe, it, expect } from "vitest";
import { validateProxyConfig } from "../src/config.js";

const base = {
  listenPort: 8080,
  backends: [{ id: "b1", tenantId: "t1", target: "http://localhost:3001" }],
  routes: [{ id: "r1", tenantId: "t1", pathPrefix: "/", backends: ["b1"], strategy: "round-robin" as const }],
  healthCheck: { enabled: true, intervalMs: 5000, timeoutMs: 1000, path: "/health" },
  circuitBreaker: { failureThreshold: 5, cooldownMs: 30000, halfOpenMaxAttempts: 2 },
};

describe("config", () => {
  it("validates good config", async () => {
    const cfg = await validateProxyConfig(base);
    expect(cfg.listenPort).toBe(8080);
  });

  it("rejects bad backend url", async () => {
    await expect(validateProxyConfig({ ...base, backends: [{ id: "b1", tenantId: "t1", target: "notaurl" }] }))
      .rejects.toThrow(/target invalid/);
  });

  it("rejects unknown backend in route", async () => {
    await expect(
      validateProxyConfig({
        ...base,
        routes: [{ id: "r1", tenantId: "t1", pathPrefix: "/", backends: ["missing"], strategy: "round-robin" }],
      })
    ).rejects.toThrow(/unknown backend/);
  });

  it("rejects health timeout >= interval", async () => {
    await expect(
      validateProxyConfig({
        ...base,
        healthCheck: { enabled: true, intervalMs: 1000, timeoutMs: 1000, path: "/" },
      })
    ).rejects.toThrow(/timeoutMs must be </);
  });

  it("validates admin jwt secret length", async () => {
    await expect(
      validateProxyConfig({
        ...base,
        admin: { listenPort: 9090, jwtSecret: "short", users: [] },
      })
    ).rejects.toThrow(/>=16 chars/);
  });

  it("requires host or pathPrefix", async () => {
    await expect(
      validateProxyConfig({
        ...base,
        routes: [{ id: "r1", tenantId: "t1", backends: ["b1"], strategy: "round-robin" }],
      })
    ).rejects.toThrow(/must have host or pathPrefix/);
  });

  it("validates pools with cycle detection", async () => {
    const cfg = await validateProxyConfig({
      ...base,
      pools: [{ id: "p1", tenantId: "t1", members: ["b1"], strategy: "round-robin" }],
      routes: [{ id: "r1", tenantId: "t1", pathPrefix: "/", backends: ["p1"], strategy: "round-robin" }],
    });
    expect(cfg.pools?.[0].id).toBe("p1");
    await expect(validateProxyConfig({
      ...base,
      pools: [
        { id: "p1", tenantId: "t1", members: ["p2"] },
        { id: "p2", tenantId: "t1", members: ["p1"] },
      ],
      routes: [{ id: "r1", tenantId: "t1", pathPrefix: "/", backends: ["p1"], strategy: "round-robin" }],
    })).rejects.toThrow(/cycle/);
  });

  it("aborts validation via signal", async () => {
    const ac = new AbortController();
    ac.abort();
    await expect(validateProxyConfig(base, ac.signal)).rejects.toThrow();
  });
});
