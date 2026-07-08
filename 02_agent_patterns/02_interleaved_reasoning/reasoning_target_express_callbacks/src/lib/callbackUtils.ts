import type { Callback } from "../db/store";

// Generic control-flow helpers written in continuation-passing style.
//
// `retry` is the Task 1 migration target: a single self-contained function
// that is easy to reason about but awkward in callback form (the recursive
// `attempt()` closure). Converting it to async/await is a clean, small win.

export function retry<T>(
  times: number,
  op: (cb: Callback<T>) => void,
  cb: Callback<T>,
): void {
  let attempts = 0;

  function attempt(): void {
    attempts += 1;
    op((err, result) => {
      if (err && attempts < times) {
        attempt();
        return;
      }
      cb(err, result);
    });
  }

  attempt();
}

// Run an array of callback-style operations one after another, collecting
// results in order. Stops at the first error (error-first convention).
export function mapSeries<I, O>(
  items: I[],
  iter: (item: I, cb: Callback<O>) => void,
  cb: Callback<O[]>,
): void {
  const results: O[] = [];

  function next(index: number): void {
    if (index >= items.length) {
      cb(null, results);
      return;
    }
    iter(items[index], (err, value) => {
      if (err) {
        cb(err);
        return;
      }
      results.push(value as O);
      next(index + 1);
    });
  }

  next(0);
}
