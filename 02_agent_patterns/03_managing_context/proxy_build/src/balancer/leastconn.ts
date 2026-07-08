import type { Node } from "../pool.js";
import type { Balancer, BalancerContext } from "./types.js";

export class LeastConnectionsBalancer implements Balancer {
  async select(nodes: Node[], ctx?: BalancerContext): Promise<Node | null> {
    ctx?.signal?.throwIfAborted();
    if (nodes.length === 0) return null;
    let best = nodes[0];
    for (const b of nodes) {
      if (b.activeConnections < best.activeConnections) best = b;
    }
    return best;
  }
}
