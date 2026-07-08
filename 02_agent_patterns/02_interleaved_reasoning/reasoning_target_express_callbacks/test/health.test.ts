import request from "supertest";
import { createApp } from "../src/app";

describe("health", () => {
  it("reports ok", async () => {
    const res = await request(createApp()).get("/health");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok" });
  });
});
