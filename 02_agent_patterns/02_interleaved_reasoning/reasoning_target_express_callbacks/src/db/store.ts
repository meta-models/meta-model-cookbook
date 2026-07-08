import { randomUUID } from "crypto";

// A tiny in-memory "database" that mimics real async I/O using Node-style
// error-first callbacks: every operation calls `cb(err)` on failure or
// `cb(null, result)` on success, and never returns a value directly.
//
// This is the lowest layer of the callback-style app. Repositories build on
// top of it, and the route handlers nest callbacks several levels deep. The
// migration tasks convert these layers to async/await.

export type Callback<T> = (err: Error | null, result?: T) => void;

export interface UserRecord {
  id: string;
  name: string;
  email: string;
}

export interface OrderRecord {
  id: string;
  userId: string;
  item: string;
  quantity: number;
  status: "pending" | "shipped";
}

const users = new Map<string, UserRecord>();
const orders = new Map<string, OrderRecord>();

// Defer to the next tick so callers cannot accidentally depend on synchronous
// behavior — exactly the trap that makes callback code hard to refactor.
function defer(fn: () => void): void {
  setImmediate(fn);
}

export function insertUser(input: Omit<UserRecord, "id">, cb: Callback<UserRecord>): void {
  defer(() => {
    const record: UserRecord = { id: randomUUID(), ...input };
    users.set(record.id, record);
    cb(null, record);
  });
}

export function findUser(id: string, cb: Callback<UserRecord>): void {
  defer(() => {
    const record = users.get(id);
    if (!record) {
      cb(new Error(`user ${id} not found`));
      return;
    }
    cb(null, record);
  });
}

export function listUsers(cb: Callback<UserRecord[]>): void {
  defer(() => cb(null, [...users.values()]));
}

export function insertOrder(input: Omit<OrderRecord, "id">, cb: Callback<OrderRecord>): void {
  defer(() => {
    const record: OrderRecord = { id: randomUUID(), ...input };
    orders.set(record.id, record);
    cb(null, record);
  });
}

export function findOrder(id: string, cb: Callback<OrderRecord>): void {
  defer(() => {
    const record = orders.get(id);
    if (!record) {
      cb(new Error(`order ${id} not found`));
      return;
    }
    cb(null, record);
  });
}

export function listOrdersByUser(userId: string, cb: Callback<OrderRecord[]>): void {
  defer(() => cb(null, [...orders.values()].filter((o) => o.userId === userId)));
}

export function updateOrderStatus(
  id: string,
  status: OrderRecord["status"],
  cb: Callback<OrderRecord>,
): void {
  defer(() => {
    const record = orders.get(id);
    if (!record) {
      cb(new Error(`order ${id} not found`));
      return;
    }
    record.status = status;
    orders.set(record.id, record);
    cb(null, record);
  });
}

// Test helper — wipe all collections between tests.
export function resetStore(): void {
  users.clear();
  orders.clear();
}
