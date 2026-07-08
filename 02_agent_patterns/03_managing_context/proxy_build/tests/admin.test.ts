import { describe, it, expect, beforeAll, afterAll } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { BackendPool } from "../src/pool.js";
import { Router } from "../src/router.js";
import { createAdminHandler, type AdminContext } from "../src/admin.js";
import { hashPassword, signJWT } from "./../src/admin_auth.js";
import { MultiRateLimiter } from "../src/ratelimit.js";

describe("admin api", () => {
  let server: http.Server;
  let port: number;
  let tokenAdmin: string;
  let tokenViewer: string;
  let pool: BackendPool;
  let router: Router;

  beforeAll(async () => {
    const adminHash = await hashPassword("secret");
    const viewerHash = await hashPassword("view");
    const cfg = {
      listenPort: 0,
      jwtSecret: "supersecretkey123456",
      users: [
        { username: "admin", passwordHash: adminHash, role: "admin" as const },
        { username: "viewer", passwordHash: viewerHash, role: "viewer" as const },
      ],
    };
    pool = new BackendPool();
    await pool.addBackend({ id: "b1", tenantId: "t1", target: "http://localhost:3001" });
    router = new Router([]);
    const rateLimiter = new MultiRateLimiter();
    const ctx: AdminContext = { pool, router, config: cfg, rateLimiter };
    const handler = createAdminHandler(ctx);
    server = http.createServer(handler);
    await new Promise<void>(r => server.listen(0, r));
    port = (server.address() as AddressInfo).port;
    tokenAdmin = await signJWT({ sub: "admin", role: "admin", tenantId: "t1", exp: Math.floor(Date.now()/1000)+3600 }, cfg.jwtSecret);
    tokenViewer = await signJWT({ sub: "viewer", role: "viewer", tenantId: "t1", exp: Math.floor(Date.now()/1000)+3600 }, cfg.jwtSecret);
  });

  afterAll(() => { server.close(); });

  function req(method: string, path: string, token?: string, body?: any): Promise<{ status: number; body: any }> {
    return new Promise((resolve, reject) => {
      const opts: http.RequestOptions = {
        hostname: "localhost",
        port,
        method,
        path,
        headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
      };
      const r = http.request(opts, res => {
        let d = ""; res.on("data", c => d += c); res.on("end", () => {
          try { resolve({ status: res.statusCode!, body: d ? JSON.parse(d) : {} }); } catch { resolve({ status: res.statusCode!, body: d }); }
        });
      });
      r.on("error", reject);
      if (body) r.write(JSON.stringify(body));
      r.end();
    });
  }

  it("login works", async () => {
    const res = await req("POST", "/login", undefined, { username: "admin", password: "secret" });
    expect(res.status).toBe(200);
    expect(res.body.token).toBeTruthy();
  });

  it("viewer can list but not modify backends", async () => {
    const list = await req("GET", "/backends", tokenViewer);
    expect(list.status).toBe(200);
    const add = await req("POST", "/backends", tokenViewer, { id: "x", tenantId: "t1", target: "http://x" });
    expect(add.status).toBe(403);
  });

  it("operator can add backend", async () => {
    const add = await req("POST", "/backends", tokenAdmin, { id: "b2", tenantId: "t1", target: "http://localhost:3002" });
    expect(add.status).toBe(201);
    expect(await pool.get("b2", "t1")).toBeTruthy();
  });

  it("admin can manage routes, viewer cannot", async () => {
    const route = { id: "r1", tenantId: "t1", pathPrefix: "/", backends: ["b1"], strategy: "round-robin" };
    const deny = await req("POST", "/routes", tokenViewer, route);
    expect(deny.status).toBe(403);
    const ok = await req("POST", "/routes", tokenAdmin, route);
    expect(ok.status).toBe(201);
    expect((await router.match({ path: "/" }, "t1"))?.id).toBe("r1");
    const del = await req("DELETE", "/routes/r1", tokenAdmin);
    expect(del.status).toBe(204);
  });

  it("tenant isolation", async () => {
    const adminHash = await hashPassword("secret2");
    const cfg2 = {
      listenPort: 0,
      jwtSecret: "supersecretkey123456",
      users: [{ username: "admin2", passwordHash: adminHash, role: "admin" as const }],
    };
    const pool2 = new BackendPool();
    await pool2.addBackend({ id: "b_t2", tenantId: "t2", target: "http://x" });
    const router2 = new Router([]);
    const ctx2: AdminContext = { pool: pool2, router: router2, config: cfg2, rateLimiter: new MultiRateLimiter() };
    const handler2 = createAdminHandler(ctx2);
    const server2 = http.createServer(handler2);
    await new Promise<void>(r => server2.listen(0, r));
    const port2 = (server2.address() as AddressInfo).port;
    const tokenT2 = await signJWT({ sub: "admin2", role: "admin", tenantId: "t2", exp: Math.floor(Date.now()/1000)+3600 }, cfg2.jwtSecret);
    
    function req2(method: string, path: string, token?: string, body?: any): Promise<{ status: number; body: any }> {
      return new Promise((resolve, reject) => {
        const opts: http.RequestOptions = {
          hostname: "localhost",
          port: port2,
          method,
          path,
          headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
        };
        const r = http.request(opts, res => {
          let d = ""; res.on("data", c => d += c); res.on("end", () => {
            try { resolve({ status: res.statusCode!, body: d ? JSON.parse(d) : {} }); } catch { resolve({ status: res.statusCode!, body: d }); }
          });
        });
        r.on("error", reject);
        if (body) r.write(JSON.stringify(body));
        r.end();
      });
    }
    
    const list = await req2("GET", "/backends", tokenT2);
    expect(list.status).toBe(200);
    expect(list.body.map((b: any) => b.id)).toEqual(["b_t2"]);
    
    server2.close();
  });
});
