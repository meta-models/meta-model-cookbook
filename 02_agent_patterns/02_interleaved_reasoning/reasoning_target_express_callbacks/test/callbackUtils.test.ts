import { retry, mapSeries } from "../src/lib/callbackUtils";

// Behavioral check for the Task 1 / Task helpers migration. Whether `retry`
// and `mapSeries` are callback-style or async/await, these expectations hold.

describe("retry", () => {
  it("returns the first success without further attempts", (done) => {
    let calls = 0;
    retry<number>(
      3,
      (cb) => {
        calls += 1;
        cb(null, 42);
      },
      (err, result) => {
        expect(err).toBeNull();
        expect(result).toBe(42);
        expect(calls).toBe(1);
        done();
      },
    );
  });

  it("retries until success", (done) => {
    let calls = 0;
    retry<string>(
      3,
      (cb) => {
        calls += 1;
        if (calls < 3) {
          cb(new Error("transient"));
          return;
        }
        cb(null, "ok");
      },
      (err, result) => {
        expect(err).toBeNull();
        expect(result).toBe("ok");
        expect(calls).toBe(3);
        done();
      },
    );
  });

  it("surfaces the last error after exhausting attempts", (done) => {
    retry<string>(
      2,
      (cb) => cb(new Error("always fails")),
      (err) => {
        expect(err).toBeInstanceOf(Error);
        expect(err?.message).toBe("always fails");
        done();
      },
    );
  });
});

describe("mapSeries", () => {
  it("maps items in order", (done) => {
    mapSeries<number, number>(
      [1, 2, 3],
      (n, cb) => cb(null, n * 2),
      (err, results) => {
        expect(err).toBeNull();
        expect(results).toEqual([2, 4, 6]);
        done();
      },
    );
  });

  it("stops at the first error", (done) => {
    mapSeries<number, number>(
      [1, 2, 3],
      (n, cb) => (n === 2 ? cb(new Error("boom")) : cb(null, n)),
      (err, results) => {
        expect(err?.message).toBe("boom");
        expect(results).toBeUndefined();
        done();
      },
    );
  });
});
