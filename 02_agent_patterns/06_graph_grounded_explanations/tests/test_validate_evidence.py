import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validate_evidence import load_json, validate


class EvidenceValidationTests(unittest.TestCase):
    def test_valid_fixture_has_full_structural_coverage(self):
        report = validate(
            load_json(ROOT / "graph.json"),
            load_json(ROOT / "examples/response-valid.json"),
        )
        self.assertTrue(report["valid"])
        self.assertEqual(report["structural_evidence_coverage"], 1.0)
        self.assertFalse(report["semantic_entailment_checked"])

    def test_unknown_nodes_and_edges_are_rejected(self):
        report = validate(
            load_json(ROOT / "graph.json"),
            load_json(ROOT / "examples/response-invalid.json"),
        )
        self.assertFalse(report["valid"])
        self.assertEqual(report["structural_evidence_coverage"], 0.0)
        self.assertTrue(any("unknown nodes" in item for item in report["violations"]))

    def test_disconnected_known_nodes_are_not_a_path(self):
        graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
        response = {
            "answer": "Claim",
            "claims": [{"text": "Claim", "evidence_paths": [["a", "b"]]}],
        }
        report = validate(graph, response)
        self.assertFalse(report["valid"])
        self.assertTrue(
            any("missing directed edges" in item for item in report["violations"])
        )


if __name__ == "__main__":
    unittest.main()
