import type { Node } from "../pool.js";

export interface BalancerContext {
  tenantId?: string;
  key?: string;
  signal?: AbortSignal;
}

export interface Balancer {
  select(nodes: Node[], ctx?: BalancerContext): Promise<Node | null>;
}
