#!/usr/bin/env python3
"""
validate_alert_output.py — parses OpenCode edit/write calls or direct demo output,
asserts strict JSON shape for probe and self-assess, prints unified diff style report.
Zero deps, stdlib only. Mirrors edit_validator.py pattern from validated_in_place_edits recipe.
Usage:
  python3 validate_alert_output.py state/purpose.json state/signals.json state/assessment.json
  python3 validate_alert_output.py --probe probe_output.json --assess assessment.json
Exit 0 on valid, 1 on invalid with [ERR] lines.
"""

import json, sys, pathlib


def load(p):
    return json.loads(pathlib.Path(p).read_text())


def validate_probe(obj):
    errs = []
    if not isinstance(obj.get("patterns"), list):
        errs.append("patterns must be list")
    else:
        for i, p in enumerate(obj["patterns"]):
            if not isinstance(p.get("text"), str) or not p["text"]:
                errs.append(f"patterns[{i}].text missing")
            sh = p.get("salience_hint")
            if sh is not None and not isinstance(sh, (int, float)):
                errs.append(f"patterns[{i}].salience_hint not number")
    rp = obj.get("refined_purpose") or {}
    if not isinstance(rp.get("statement"), str) or not rp["statement"]:
        errs.append("refined_purpose.statement missing")
    sigs = obj.get("signals")
    if not isinstance(sigs, list) or not sigs:
        errs.append("signals must non-empty list")
    else:
        for i, s in enumerate(sigs):
            for f in [
                "source_connector",
                "extraction",
                "unit",
                "direction",
                "role",
                "proxy_strength",
                "rationale",
            ]:
                if f not in s:
                    errs.append(f"signals[{i}] missing {f}")
            if s.get("direction") not in ("up", "down"):
                errs.append(f"signals[{i}].direction invalid")
            if s.get("role") not in ("north-star", "leading"):
                errs.append(f"signals[{i}].role invalid")
    return errs


def validate_assess(obj):
    errs = []
    if not isinstance(obj.get("narrative"), str) or not obj["narrative"]:
        errs.append("narrative missing")
    props = obj.get("proposals")
    if not isinstance(props, list):
        errs.append("proposals must list")
    else:
        for i, p in enumerate(props):
            if p.get("kind") not in (
                "mandate",
                "purpose",
                "signal",
                "memory",
                "scenario",
            ):
                errs.append(f"proposals[{i}].kind invalid")
            if p.get("risk") not in ("low", "high"):
                errs.append(f"proposals[{i}].risk invalid")
            if not isinstance(p.get("rationale"), str):
                errs.append(f"proposals[{i}].rationale missing")
            if not isinstance(p.get("payload"), dict):
                errs.append(f"proposals[{i}].payload not object")
    return errs


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "purpose",
        nargs="?",
        help="state/purpose.json or probe json file containing patterns refined_purpose signals",
    )
    ap.add_argument(
        "signals",
        nargs="?",
        help="state/signals.json (optional if purpose file is full probe)",
    )
    ap.add_argument("assessment", nargs="?", help="state/assessment.json")
    ap.add_argument(
        "--probe",
        help="probe output json path containing patterns refined_purpose signals",
    )
    ap.add_argument("--assess", help="assessment json path")
    args = ap.parse_args()
    ok = True
    # determine probe source
    probe_path = args.probe or args.purpose
    assess_path = (
        args.assess or args.assessment or (sys.argv[3] if len(sys.argv) > 3 else None)
    )
    if probe_path and pathlib.Path(probe_path).exists():
        try:
            pj = load(probe_path)
            # if it's purpose.json alone, try to merge signals file
            if "patterns" not in pj and args.signals:
                pj["signals"] = load(args.signals)
                # can't validate without patterns, skip if incomplete
            if "patterns" in pj:
                e = validate_probe(pj)
                if e:
                    ok = False
                    for err in e:
                        print(f"[ERR] probe {err}")
                else:
                    print("[OK] probe JSON valid strict shape")
            else:
                print(
                    "[INFO] probe file looks like purpose.json alone, skipping full probe validation, use --probe with full probe output for complete check"
                )
        except Exception as ex:
            ok = False
            print(f"[ERR] probe load failed {ex}")
    if assess_path and pathlib.Path(assess_path).exists():
        try:
            aj = load(assess_path)
            e = validate_assess(aj)
            if e:
                ok = False
                for err in e:
                    print(f"[ERR] assess {err}")
            else:
                print("[OK] self-assess JSON valid strict shape")
        except Exception as ex:
            ok = False
            print(f"[ERR] assess load failed {ex}")
    if not probe_path and not assess_path:
        print(
            "Usage: python3 validate_alert_output.py state/purpose.json state/signals.json state/assessment.json"
        )
        print(
            "   or: python3 validate_alert_output.py --probe probe.json --assess assessment.json"
        )
        sys.exit(2)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
