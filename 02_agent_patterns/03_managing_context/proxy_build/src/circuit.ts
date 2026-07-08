export type CircuitState = "closed" | "open" | "half_open";

export interface CircuitBreakerOptions {
  failureThreshold: number;
  cooldownMs: number;
  halfOpenMaxAttempts: number;
}

function delay(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const onAbort = () => { clearImmediate(im); reject(signal?.reason); };
    const im = setImmediate(() => { signal?.removeEventListener("abort", onAbort); resolve(); });
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

class SingleBreaker {
  private state: CircuitState = "closed";
  private failures = 0;
  private openedAt = 0;
  private halfOpenAttempts = 0;

  constructor(private opts: CircuitBreakerOptions) {}

  async canRequest(now = Date.now(), signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    await delay(signal);
    if (this.state === "closed") return true;
    if (this.state === "open") {
      if (now - this.openedAt >= this.opts.cooldownMs) {
        this.state = "half_open";
        this.halfOpenAttempts = 0;
        return true;
      }
      return false;
    }
    return this.halfOpenAttempts < this.opts.halfOpenMaxAttempts;
  }

  async recordSuccess(signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    this.failures = 0;
    this.state = "closed";
    this.halfOpenAttempts = 0;
  }

  async recordFailure(now = Date.now(), signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    if (this.state === "half_open") {
      this.state = "open";
      this.openedAt = now;
      this.failures = 0;
      this.halfOpenAttempts = 0;
      return;
    }
    this.failures += 1;
    if (this.failures >= this.opts.failureThreshold) {
      this.state = "open";
      this.openedAt = now;
      this.failures = 0;
    }
  }

  async getState(signal?: AbortSignal): Promise<CircuitState> {
    signal?.throwIfAborted();
    await delay(signal);
    return this.state;
  }

  async recordAttempt(signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await delay(signal);
    if (this.state === "half_open") this.halfOpenAttempts += 1;
  }
}

export class CircuitBreakerRegistry {
  private breakers = new Map<string, SingleBreaker>();
  constructor(private opts: CircuitBreakerOptions) {}

  private key(tenantId: string, id: string): string {
    return `${tenantId}:${id}`;
  }

  private getBreaker(tenantId: string, id: string): SingleBreaker {
    const k = this.key(tenantId, id);
    let b = this.breakers.get(k);
    if (!b) {
      b = new SingleBreaker(this.opts);
      this.breakers.set(k, b);
    }
    return b;
  }

  async canRequest(tenantId: string, id: string, now = Date.now(), signal?: AbortSignal): Promise<boolean> {
    return this.getBreaker(tenantId, id).canRequest(now, signal);
  }

  async recordAttempt(tenantId: string, id: string, signal?: AbortSignal): Promise<void> {
    return this.getBreaker(tenantId, id).recordAttempt(signal);
  }

  async recordSuccess(tenantId: string, id: string, signal?: AbortSignal): Promise<void> {
    return this.getBreaker(tenantId, id).recordSuccess(signal);
  }

  async recordFailure(tenantId: string, id: string, now = Date.now(), signal?: AbortSignal): Promise<void> {
    return this.getBreaker(tenantId, id).recordFailure(now, signal);
  }

  async getState(tenantId: string, id: string, signal?: AbortSignal): Promise<CircuitState> {
    return this.getBreaker(tenantId, id).getState(signal);
  }
}
