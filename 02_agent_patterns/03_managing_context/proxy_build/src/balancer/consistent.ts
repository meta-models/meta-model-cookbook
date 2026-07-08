import type { Node } from "../pool.js";
import type { Balancer, BalancerContext } from "./types.js";

function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

interface RingEntry {
  hash: number;
  node: Node;
}

export class ConsistentHashBalancer implements Balancer {
  private replicas = 100;
  private ringCache = new WeakMap<object, RingEntry[]>();

  async select(nodes: Node[], ctx?: BalancerContext): Promise<Node | null> {
    ctx?.signal?.throwIfAborted();
    if (nodes.length === 0) return null;
    const key = ctx?.key ?? "";
    if (!key) return nodes[0];
    const ring = this.buildRing(nodes);
    const h = hashString(key);
    let lo = 0, hi = ring.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (ring[mid].hash >= h) hi = mid;
      else lo = mid + 1;
    }
    if (ring[lo].hash < h) lo = 0;
    return ring[lo].node;
  }

  private buildRing(nodes: Node[]): RingEntry[] {
    const cacheKey = nodes as unknown as object;
    const cached = this.ringCache.get(cacheKey);
    if (cached) return cached;
    const ring: RingEntry[] = [];
    for (const b of nodes) {
      for (let i = 0; i < this.replicas; i++) {
        ring.push({ hash: hashString(`${b.id}#${i}`), node: b });
      }
    }
    ring.sort((a, b) => a.hash - b.hash);
    return ring;
  }
}
