import type { LBStrategy } from "../config.js";
import { RoundRobinBalancer, LeastConnectionsBalancer, WeightedBalancer, ConsistentHashBalancer } from "./index.js";
import type { Balancer } from "./types.js";

export class BalancerFactory {
  static create(strategy: LBStrategy): Balancer {
    switch (strategy) {
      case "least-connections": return new LeastConnectionsBalancer();
      case "weighted": return new WeightedBalancer();
      case "consistent-hash": return new ConsistentHashBalancer();
      default: return new RoundRobinBalancer();
    }
  }
}
