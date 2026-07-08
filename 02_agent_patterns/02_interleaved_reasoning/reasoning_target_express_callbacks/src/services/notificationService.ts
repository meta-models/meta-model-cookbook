import { EventEmitter } from "events";
import type { Callback } from "../db/store";

// Task 4 migration target: event-emitter + callback style. `onceShipped`
// resolves when the matching "shipped" event fires, or errors on timeout.
// The idiomatic async/await version uses `events.once` with an AbortSignal,
// which removes the manual listener bookkeeping below.

export const notifications = new EventEmitter();

export function emitShipped(orderId: string): void {
  notifications.emit("shipped", orderId);
}

export function onceShipped(orderId: string, timeoutMs: number, cb: Callback<string>): void {
  const onShipped = (id: string): void => {
    if (id === orderId) {
      cleanup();
      cb(null, id);
    }
  };

  const timer = setTimeout(() => {
    cleanup();
    cb(new Error(`timed out waiting for order ${orderId} to ship`));
  }, timeoutMs);

  function cleanup(): void {
    notifications.off("shipped", onShipped);
    clearTimeout(timer);
  }

  notifications.on("shipped", onShipped);
}
