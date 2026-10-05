"""Check that answer claims cite nodes joined by supplied directed graph edges."""

import argparse
import json
from itertools import pairwise
from pathlib import Path
from typing import Any


class EvidenceError(ValueError):
    """Raised for malformed graph or answer data."""


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def validate(graph: Any, response: Any) -> dict[str, Any]:
    if not isinstance(graph, dict) or not isinstance(response, dict):
        raise EvidenceError("graph and response must be JSON objects")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    claims = response.get("claims")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise EvidenceError("graph nodes and edges must be arrays")
    if not isinstance(claims, list) or not isinstance(response.get("answer"), str):
        raise EvidenceError("response requires a string answer and a claims array")
    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not node["id"]
        ):
            raise EvidenceError(f"nodes[{index}] requires a non-empty id")
        if node["id"] in node_ids:
            raise EvidenceError(f"duplicate node id: {node['id']}")
        node_ids.add(node["id"])
    relationships: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise EvidenceError(f"edges[{index}] must be an object")
        source, target = edge.get("from"), edge.get("to")
        if (
            not isinstance(source, str)
            or not isinstance(target, str)
            or source not in node_ids
            or target not in node_ids
        ):
            raise EvidenceError(f"edges[{index}] references an unknown node")
        relationships.add((source, target))

    violations: list[str] = []
    valid_claims = 0
    if not claims:
        violations.append("response must contain at least one claim")
    for claim_index, claim in enumerate(claims):
        if (
            not isinstance(claim, dict)
            or not isinstance(claim.get("text"), str)
            or not claim["text"].strip()
        ):
            violations.append(f"claims[{claim_index}] requires non-empty text")
            continue
        paths = claim.get("evidence_paths")
        if not isinstance(paths, list) or not paths:
            violations.append(
                f"claims[{claim_index}] requires at least one evidence path"
            )
            continue
        path_errors: list[str] = []
        for path_index, path in enumerate(paths):
            if (
                not isinstance(path, list)
                or not path
                or not all(isinstance(item, str) for item in path)
            ):
                path_errors.append(
                    f"path {path_index} must be a non-empty array of node IDs"
                )
                continue
            unknown = [node_id for node_id in path if node_id not in node_ids]
            if unknown:
                path_errors.append(
                    f"path {path_index} has unknown nodes: {', '.join(unknown)}"
                )
                continue
            missing_edges = [
                f"{left}->{right}"
                for left, right in pairwise(path)
                if (left, right) not in relationships
            ]
            if missing_edges:
                path_errors.append(
                    f"path {path_index} has missing directed edges: {', '.join(missing_edges)}"
                )
        if path_errors:
            violations.extend(f"claims[{claim_index}] {error}" for error in path_errors)
        else:
            valid_claims += 1

    total_claims = len(claims)
    return {
        "valid": not violations,
        "claims_total": total_claims,
        "claims_with_structurally_valid_evidence": valid_claims,
        "structural_evidence_coverage": valid_claims / total_claims
        if total_claims
        else 0.0,
        "violations": violations,
        "semantic_entailment_checked": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", help="graph JSON with nodes and directed edges")
    parser.add_argument("response", help="answer JSON with claim evidence paths")
    args = parser.parse_args()
    try:
        report = validate(load_json(args.graph), load_json(args.response))
    except (OSError, json.JSONDecodeError, EvidenceError) as exc:
        print(json.dumps({"valid": False, "violations": [str(exc)]}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
