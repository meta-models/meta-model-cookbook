import request from "supertest";
import { createApp } from "../src/app";
import { resetStore } from "../src/db/store";

// These tests exercise the HTTP surface, so they hold whether the internals
// are callback-style or async/await. That is exactly what makes them a safe
// check for the migration: behavior must not change.

const app = createApp();

beforeEach(() => resetStore());

describe("users", () => {
  it("creates a user and reads it back", async () => {
    const create = await request(app)
      .post("/users")
      .send({ name: "Ada Lovelace", email: "ada@example.com" });
    expect(create.status).toBe(201);
    expect(create.body.id).toBeDefined();
    expect(create.body.name).toBe("Ada Lovelace");

    const read = await request(app).get(`/users/${create.body.id}`);
    expect(read.status).toBe(200);
    expect(read.body.email).toBe("ada@example.com");
  });

  it("rejects invalid input with 400", async () => {
    const res = await request(app).post("/users").send({ name: "", email: "nope" });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/name is required/);
  });

  it("returns 404 for a missing user", async () => {
    const res = await request(app).get("/users/does-not-exist");
    expect(res.status).toBe(404);
    expect(res.body.error).toMatch(/not found/);
  });

  it("lists created users", async () => {
    await request(app).post("/users").send({ name: "Grace Hopper", email: "grace@example.com" });
    const res = await request(app).get("/users");
    expect(res.status).toBe(200);
    expect(res.body).toHaveLength(1);
  });
});
