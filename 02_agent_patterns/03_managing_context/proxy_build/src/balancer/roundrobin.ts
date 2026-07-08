import type { Node } from "../pool.js";
import type { Balancer, BalancerContext } from "./types.js";

export class RoundRobinBalancer implements Balancer {
  private idx = 0;
  async select(nodes: Node[], ctx?: BalancerContext): Promise<Node | null> {
    ctx?.signal?.throwIfAborted();
    if (nodes.length === 0) return null;
    const b = nodes[this.idx % nodes.length];
    this.idx = (this.idx + 1) % nodes.length;
    return b;
  }
}
