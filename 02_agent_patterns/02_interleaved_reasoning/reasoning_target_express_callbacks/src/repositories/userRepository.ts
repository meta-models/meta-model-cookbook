import * as store from "../db/store";
import type { Callback, UserRecord } from "../db/store";
import { validateUserInput } from "../lib/validate";

// Task 2 migration target: a single file of nested error-first callbacks.
// `createUser` validates, then inserts — two levels of nesting with manual
// error forwarding at each step.

export function createUser(body: unknown, cb: Callback<UserRecord>): void {
  validateUserInput(body, (validationErr, input) => {
    if (validationErr) {
      cb(validationErr);
      return;
    }
    store.insertUser(input as { name: string; email: string }, (insertErr, user) => {
      if (insertErr) {
        cb(insertErr);
        return;
      }
      cb(null, user);
    });
  });
}

export function getUser(id: string, cb: Callback<UserRecord>): void {
  store.findUser(id, (err, user) => {
    if (err) {
      cb(err);
      return;
    }
    cb(null, user);
  });
}

export function getAllUsers(cb: Callback<UserRecord[]>): void {
  store.listUsers(cb);
}
