import { describe, it, expect } from "vitest";
import { Router } from "../src/router.js";

describe("router", () => {
  it("matches path prefix longest first", async () => {
    const r = new Router([
      { id: "a", tenantId: "t1", pathPrefix: "/api", backends: ["b1"], strategy: "round-robin" },
      { id: "b", tenantId: "t1", pathPrefix: "/api/v2", backends: ["b1"], strategy: "round-robin" },
      { id: "c", tenantId: "t1", pathPrefix: "/", backends: ["b1"], strategy: "round-robin" },
    ]);
    expect((await r.match({ path: "/api/v2/users" }, "t1"))?.id).toBe("b");
    expect((await r.match({ path: "/api/foo" }, "t1"))?.id).toBe("a");
    expect((await r.match({ path: "/other" }, "t1"))?.id).toBe("c");
  });

  it("matches host", async () => {
    const r = new Router([
      { id: "a", tenantId: "t1", host: "foo.example.com", pathPrefix: "/", backends: ["b1"], strategy: "round-robin" },
      { id: "b", tenantId: "t1", host: "bar.example.com", pathPrefix: "/", backends: ["b1"], strategy: "round-robin" },
    ]);
    expect((await r.match({ host: "foo.example.com:8080", path: "/" }, "t1"))?.id).toBe("a");
    expect((await r.match({ host: "bar.example.com", path: "/" }, "t1"))?.id).toBe("b");
  });

  it("requires both host and path when set", async () => {
    const r = new Router([
      { id: "a", tenantId: "t1", host: "x.com", pathPrefix: "/api", backends: ["b1"], strategy: "round-robin" },
    ]);
    expect((await r.match({ host: "x.com", path: "/api/foo" }, "t1"))?.id).toBe("a");
    expect(await r.match({ host: "y.com", path: "/api/foo" }, "t1")).toBeNull();
    expect(await r.match({ host: "x.com", path: "/other" }, "t1")).toBeNull();
  });

  it("upsert and remove", async () => {
    const r = new Router([]);
    await r.upsert({ id: "a", tenantId: "t1", pathPrefix: "/", backends: ["b"], strategy: "round-robin" });
    expect((await r.match({ path: "/" }, "t1"))?.id).toBe("a");
    expect(await r.remove("a", "t1")).toBe(true);
    expect(await r.match({ path: "/" }, "t1")).toBeNull();
  });

  it("aborts via signal", async () => {
    const r = new Router([]);
    const ac = new AbortController(); ac.abort();
    await expect(r.match({ path: "/" }, "t1", ac.signal)).rejects.toThrow();
  });

  it("tenant isolation", async () => {
    const r = new Router([
      { id: "a", tenantId: "t1", pathPrefix: "/", backends: ["b1"], strategy: "round-robin" },
      { id: "b", tenantId: "t2", pathPrefix: "/", backends: ["b2"], strategy: "round-robin" },
    ]);
    expect((await r.match({ path: "/" }, "t1"))?.id).toBe("a");
    expect((await r.match({ path: "/" }, "t2"))?.id).toBe("b");
    expect(await r.match({ path: "/" }, "t3")).toBeNull();
  });
});
