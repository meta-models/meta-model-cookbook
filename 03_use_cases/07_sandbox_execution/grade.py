#!/usr/bin/env python3
"""
Grade pred.patch with the canonical SWE-bench Docker harness.

This is the "for real" check: the harness builds the per-instance image, applies
our source patch + the task's held-out test_patch, runs FAIL_TO_PASS and the full
PASS_TO_PASS regression set in a fresh container, and reports resolved / not.

Usage:  python grade.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_ID = "sandbox-demo"


def main():
    inst = json.load(open(f"{HERE}/task.json"))[0]
    patch = open(f"{HERE}/pred.patch").read()
    preds = [{
        "instance_id": inst["instance_id"],
        "model_name_or_path": "muse-spark-1.1",
        "model_patch": patch,
    }]
    json.dump(preds, open(f"{HERE}/preds.json", "w"))

    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", f"{HERE}/task.json",
        "--predictions_path", f"{HERE}/preds.json",
        "--run_id", RUN_ID,
        "--namespace", "none",     # build/run locally (matches the cached env image)
        "--cache_level", "env",
        "--max_workers", "1",
        "--timeout", "2400",
    ]
    subprocess.run(cmd, cwd=HERE)

    report = f"{HERE}/muse-spark-1.1.{RUN_ID}.json"
    if os.path.exists(report):
        r = json.load(open(report))
        resolved = r.get("resolved_instances", 0)
        total = r.get("submitted_instances", r.get("total_instances", 1))
        print(f"\n{'✓' if resolved else '✗'} resolved {resolved}/{total}  (report: {report})")
    else:
        print("\nno report written — check the harness output above")


if __name__ == "__main__":
    main()
