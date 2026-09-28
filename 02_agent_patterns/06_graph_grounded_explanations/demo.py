"""Ask Muse Spark for graph-cited repository explanations and validate references."""

import json
import os
from pathlib import Path
from time import perf_counter

from openai import OpenAI
from validate_evidence import load_json, validate

ROOT = Path(__file__).resolve().parent
SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "repository_explanation",
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "evidence_paths": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                        "required": ["text", "evidence_paths"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["answer", "claims"],
            "additionalProperties": False,
        },
    },
}


def main() -> int:
    if not os.environ.get("MODEL_API_KEY"):
        raise SystemExit(
            "Set MODEL_API_KEY in your environment; never put it in source files."
        )
    graph = load_json(ROOT / "graph.json")
    question = (ROOT / "question.txt").read_text(encoding="utf-8")
    client = OpenAI(
        base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"]
    )
    started = perf_counter()
    result = client.chat.completions.create(
        model="muse-spark-1.3",
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer only from the supplied synthetic repository graph. Return a concise answer "
                    "and atomic claims. For each claim, include one or more directed evidence_paths as "
                    "ordered node IDs. Do not invent files, functions, nodes, or edges. A path is a "
                    "structural citation, not proof of semantic entailment."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question, "graph": graph}),
            },
        ],
        response_format=SCHEMA,
    )
    elapsed_ms = (perf_counter() - started) * 1000
    message = result.choices[0].message
    if not message.content:
        raise SystemExit("Muse Spark returned no JSON content.")
    response = json.loads(message.content)
    report = validate(graph, response)
    record = {
        "response": response,
        "validation": report,
        "usage": {
            "prompt_tokens": result.usage.prompt_tokens if result.usage else None,
            "completion_tokens": result.usage.completion_tokens
            if result.usage
            else None,
            "total_tokens": result.usage.total_tokens if result.usage else None,
        },
        "elapsed_ms": round(elapsed_ms, 2),
        "semantic_entailment_checked": False,
    }
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
