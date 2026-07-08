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

export class WeightedBalancer implements Balancer {
  private counter = 0;
  async select(nodes: Node[], ctx?: BalancerContext): Promise<Node | null> {
    ctx?.signal?.throwIfAborted();
    if (nodes.length === 0) return null;
    const total = nodes.reduce((sum, b) => sum + (b.weight ?? 1), 0);
    if (total <= 0) return nodes[0];
    const seed = ctx?.key ? hashString(ctx.key) : this.counter++;
    const pick = seed % total;
    let acc = 0;
    for (const b of nodes) {
      acc += b.weight ?? 1;
      if (pick < acc) return b;
    }
    return nodes[nodes.length - 1];
  }
}
