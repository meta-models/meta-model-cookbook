import type { Callback } from "../db/store";

export interface UserInput {
  name: string;
  email: string;
}

export interface OrderInput {
  userId: string;
  item: string;
  quantity: number;
}

// Validation in callback form. Returns the cleaned value via `cb(null, value)`
// or an Error via `cb(err)`. Repositories call these before touching the store,
// producing the first level of callback nesting.

export function validateUserInput(body: unknown, cb: Callback<UserInput>): void {
  const data = body as Record<string, unknown>;
  if (!data || typeof data.name !== "string" || data.name.trim() === "") {
    cb(new Error("name is required"));
    return;
  }
  if (typeof data.email !== "string" || !data.email.includes("@")) {
    cb(new Error("a valid email is required"));
    return;
  }
  cb(null, { name: data.name.trim(), email: data.email.trim() });
}

export function validateOrderInput(body: unknown, cb: Callback<OrderInput>): void {
  const data = body as Record<string, unknown>;
  if (!data || typeof data.userId !== "string" || data.userId.trim() === "") {
    cb(new Error("userId is required"));
    return;
  }
  if (typeof data.item !== "string" || data.item.trim() === "") {
    cb(new Error("item is required"));
    return;
  }
  if (typeof data.quantity !== "number" || !Number.isInteger(data.quantity) || data.quantity < 1) {
    cb(new Error("quantity must be a positive integer"));
    return;
  }
  cb(null, { userId: data.userId.trim(), item: data.item.trim(), quantity: data.quantity });
}
