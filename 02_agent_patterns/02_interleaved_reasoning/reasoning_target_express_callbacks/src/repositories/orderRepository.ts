import * as store from "../db/store";
import type { Callback, OrderRecord } from "../db/store";
import * as userRepo from "./userRepository";
import { validateOrderInput } from "../lib/validate";

// Task 3 migration target: this file depends on userRepository. To migrate it
// to async/await you must reason about ordering — userRepository.getUser is
// callback-based, so either migrate it first or wrap it. That dependency order
// is the point of the task.
//
// `createOrder` is three levels deep: validate -> check the user exists ->
// insert the order.

export function createOrder(body: unknown, cb: Callback<OrderRecord>): void {
  validateOrderInput(body, (validationErr, input) => {
    if (validationErr) {
      cb(validationErr);
      return;
    }
    userRepo.getUser(input!.userId, (userErr) => {
      if (userErr) {
        cb(userErr);
        return;
      }
      store.insertOrder({ ...input!, status: "pending" }, (insertErr, order) => {
        if (insertErr) {
          cb(insertErr);
          return;
        }
        cb(null, order);
      });
    });
  });
}

export function getOrdersForUser(userId: string, cb: Callback<OrderRecord[]>): void {
  userRepo.getUser(userId, (userErr) => {
    if (userErr) {
      cb(userErr);
      return;
    }
    store.listOrdersByUser(userId, cb);
  });
}

export function shipOrder(id: string, cb: Callback<OrderRecord>): void {
  store.findOrder(id, (findErr, order) => {
    if (findErr) {
      cb(findErr);
      return;
    }
    store.updateOrderStatus(order!.id, "shipped", (updateErr, updated) => {
      if (updateErr) {
        cb(updateErr);
        return;
      }
      cb(null, updated);
    });
  });
}
