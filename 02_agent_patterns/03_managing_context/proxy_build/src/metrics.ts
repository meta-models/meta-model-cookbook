interface TenantMetrics {
  requests: number;
  errors: number;
  latencySum: number;
  latencyCount: number;
}

export class Metrics {
  private requests = 0;
  private errors = 0;
  private byStatus = new Map<number, number>();
  private byRoute = new Map<string, number>();
  private byTenant = new Map<string, TenantMetrics>();
  private latencySum = 0;
  private latencyCount = 0;

  async record(tenantId: string, routeId: string | undefined, status: number, latencyMs: number, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    this.requests += 1;
    if (status >= 500) this.errors += 1;
    this.byStatus.set(status, (this.byStatus.get(status) ?? 0) + 1);
    if (routeId) this.byRoute.set(`${tenantId}:${routeId}`, (this.byRoute.get(`${tenantId}:${routeId}`) ?? 0) + 1);
    this.latencySum += latencyMs;
    this.latencyCount += 1;

    const tm = this.byTenant.get(tenantId) ?? { requests: 0, errors: 0, latencySum: 0, latencyCount: 0 };
    tm.requests += 1;
    if (status >= 500) tm.errors += 1;
    tm.latencySum += latencyMs;
    tm.latencyCount += 1;
    this.byTenant.set(tenantId, tm);
  }

  async snapshot(signal?: AbortSignal) {
    signal?.throwIfAborted();
    await new Promise(r => setImmediate(r));
    const byTenant: Record<string, { requests: number; errors: number; avgLatencyMs: number }> = {};
    for (const [tenantId, m] of this.byTenant) {
      byTenant[tenantId] = {
        requests: m.requests,
        errors: m.errors,
        avgLatencyMs: m.latencyCount ? m.latencySum / m.latencyCount : 0,
      };
    }
    return {
      requests: this.requests,
      errors: this.errors,
      byStatus: Object.fromEntries(this.byStatus),
      byRoute: Object.fromEntries(this.byRoute),
      byTenant,
      avgLatencyMs: this.latencyCount ? this.latencySum / this.latencyCount : 0,
    };
  }
}
