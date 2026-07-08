export interface RateLimitConfig {
  rps: number;
  burst: number;
}

interface Bucket {
  tokens: number;
  last: number;
}

export class RateLimiter {
  private buckets = new Map<string, Bucket>();

  constructor(private cfg: RateLimitConfig) {}

  async allow(key: string, now = Date.now(), signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    const b = this.buckets.get(key) ?? { tokens: this.cfg.burst, last: now };
    const elapsed = (now - b.last) / 1000;
    b.tokens = Math.min(this.cfg.burst, b.tokens + elapsed * this.cfg.rps);
    b.last = now;
    if (b.tokens >= 1) {
      b.tokens -= 1;
      this.buckets.set(key, b);
      return true;
    }
    this.buckets.set(key, b);
    return false;
  }

  async reset(signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    this.buckets.clear();
  }
}

export class MultiRateLimiter {
  private limiters = new Map<string, RateLimiter>();
  private configs = new Map<string, RateLimitConfig>();

  private key(tenantId: string, routeId: string): string {
    return `${tenantId}:${routeId}`;
  }

  async setRoute(tenantId: string, routeId: string, cfg: RateLimitConfig | undefined, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    const k = this.key(tenantId, routeId);
    if (cfg) {
      this.configs.set(k, cfg);
      this.limiters.set(k, new RateLimiter(cfg));
    } else {
      this.configs.delete(k);
      this.limiters.delete(k);
    }
  }

  async allow(tenantId: string, routeId: string, key: string, now = Date.now(), signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    const k = this.key(tenantId, routeId);
    const limiter = this.limiters.get(k);
    if (!limiter) return true;
    return limiter.allow(key, now, signal);
  }
}
