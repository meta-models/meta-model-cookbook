import request from "supertest";
import { createApp } from "../src/app";
import { resetStore } from "../src/db/store";
import { notifications, onceShipped } from "../src/services/notificationService";

const app = createApp();

beforeEach(() => resetStore());
afterEach(() => notifications.removeAllListeners());

async function createUser(): Promise<string> {
  const res = await request(app)
    .post("/users")
    .send({ name: "Alan Turing", email: "alan@example.com" });
  return res.body.id as string;
}

describe("orders", () => {
  it("creates an order for an existing user", async () => {
    const userId = await createUser();
    const res = await request(app)
      .post("/orders")
      .send({ userId, item: "Widget", quantity: 3 });
    expect(res.status).toBe(201);
    expect(res.body.status).toBe("pending");
    expect(res.body.userId).toBe(userId);
  });

  it("refuses to create an order for an unknown user", async () => {
    const res = await request(app)
      .post("/orders")
      .send({ userId: "ghost", item: "Widget", quantity: 1 });
    expect(res.status).toBe(404);
  });

  it("validates order input", async () => {
    const userId = await createUser();
    const res = await request(app)
      .post("/orders")
      .send({ userId, item: "Widget", quantity: 0 });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/quantity/);
  });

  it("ships an order and emits a notification", async () => {
    const userId = await createUser();
    const created = await request(app)
      .post("/orders")
      .send({ userId, item: "Widget", quantity: 1 });
    const orderId = created.body.id as string;

    const shipped = new Promise<string>((resolve, reject) => {
      onceShipped(orderId, 1000, (err, id) => (err ? reject(err) : resolve(id as string)));
    });

    const res = await request(app).post(`/orders/${orderId}/ship`);
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("shipped");

    await expect(shipped).resolves.toBe(orderId);
  });

  it("lists orders for a user", async () => {
    const userId = await createUser();
    await request(app).post("/orders").send({ userId, item: "A", quantity: 1 });
    await request(app).post("/orders").send({ userId, item: "B", quantity: 2 });
    const res = await request(app).get(`/orders/user/${userId}`);
    expect(res.status).toBe(200);
    expect(res.body).toHaveLength(2);
  });
});
