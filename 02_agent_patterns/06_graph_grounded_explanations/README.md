# Graph-grounded repository explanations with Muse Spark

|  |  |
|---|---|
| **Section** | [Agent patterns](https://dev.meta.ai/docs/cookbook#agent-patterns) |
| **Time to complete** | ~20 min |
| **Model** | `muse-spark-1.3` |
| **Language** | Python |
| **Harness** | OpenAI Python SDK |
| **Prerequisites** | Python 3.10+, an API key, and the `openai` package |

## Summary

This recipe sends Muse Spark a small directed graph of files, functions, and module relationships. The model returns an explanation as structured JSON with an ordered node path for each claim. A local validator checks that every cited node exists and that each adjacent pair follows a supplied directed edge.

The check validates citation structure only. It cannot establish that a natural-language claim is true or semantically entailed by the graph. Treat the report as a traceability signal and inspect the cited source evidence before relying on an answer.

## Run the offline example

From this directory, validate the included response without an API key:

```bash
python3 validate_evidence.py graph.json examples/response-valid.json
```

The report should say `"valid": true`, show full structural evidence coverage, and set `"semantic_entailment_checked": false`. Try the deliberately invalid response:

```bash
python3 validate_evidence.py graph.json examples/response-invalid.json
```

It exits `1` and reports the unknown node references. Run the offline tests:

```bash
python3 -m unittest discover -s tests -v
```

## Call Muse Spark

Install the SDK and set the canonical API key environment variable:

```bash
python3 -m pip install -r requirements.txt
export MODEL_API_KEY="<your-key>"
python3 demo.py
```

The client uses `https://api.meta.ai/v1` and `muse-spark-1.3`. Never commit or paste the key into a source file. The program prints the structured answer, path-validation results, API-reported token usage, and end-to-end elapsed time. It does not estimate dollar cost.

## The evidence contract

Each response claim has `text` and one or more `evidence_paths`. A path is an ordered array of node IDs. Every ID must exist in `graph.json`, and each consecutive pair must be a directed edge in that graph. Multiple paths are allowed when a claim needs more than one route through the graph.

The included fixture is intentionally synthetic and small. A real repository workflow would first need a tested extractor for the target languages and a source-location map so a reviewer can open the cited file and symbol. This recipe does not ingest repositories, run graph retrieval, compare orchestration strategies, or evaluate the semantic correctness of model-generated claims.

## What to record

For repeated runs, retain the question, graph revision, model ID, prompt revision, validation report, API-reported prompt/completion token usage, and elapsed time. Compare variants on the same graph and questions. Report structural path coverage separately from human-judged factual correctness; the validator is not an independent semantic judge.
