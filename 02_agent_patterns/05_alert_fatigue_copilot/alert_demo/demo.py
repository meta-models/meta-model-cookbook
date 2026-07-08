#!/usr/bin/env python3
"""
Muse Spark Alert Fatigue Copilot demo — Meta Model API via the OpenAI SDK.
Reads a synthetic alert feed, probes patterns, chats, and self-assesses.

Canonical cookbook config (see CONTRIBUTING.md):
  SDK      OpenAI Python SDK (`from openai import OpenAI`)
  Base URL https://api.meta.ai/v1
  Model    muse-spark-1.1
  Key env  MODEL_API_KEY
"""

import datetime
import json
import os
import pathlib
import sys
import textwrap

from openai import OpenAI

ROOT = pathlib.Path(__file__).parent.resolve()
DATA = ROOT / "data" / "synthetic_alerts.json"
PROMPTS = ROOT / "prompts"
STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)

BASE_URL = os.environ.get("MODEL_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.environ.get("MODEL_NAME", "muse-spark-1.1")

if "MODEL_API_KEY" not in os.environ:
    print(
        "Set MODEL_API_KEY. "
        "For local dev you can create a .env file with MODEL_API_KEY=...",
        file=sys.stderr,
    )
    sys.exit(1)

# The OpenAI SDK does not auto-read MODEL_API_KEY, so pass it explicitly.
client = OpenAI(base_url=BASE_URL, api_key=os.environ["MODEL_API_KEY"])


def call_muse(system, user, max_tokens=4096):
    resp = client.responses.create(
        model=MODEL,
        max_output_tokens=max_tokens,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
    )
    return resp.output_text


def extract_json(text):
    start = text.find("{")
    if start == -1:
        raise ValueError("no json")
    depth = 0
    ins = False
    esc = False
    for i, ch in enumerate(text[start:], start):
        if ins:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                ins = False
            continue
        if ch == '"':
            ins = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced json")


def build_digest(alerts):
    total = len(alerts)
    recurring = sum(1 for a in alerts if a.get("recurring"))
    oneoff = total - recurring
    silenced = sum(1 for a in alerts if a.get("silenced"))
    times = [
        datetime.datetime.fromisoformat(a["timestamp"].replace("Z", "")) for a in alerts
    ]
    span_days = max((max(times) - min(times)).days, 1)
    per_day = round(total / span_days, 1)
    from collections import Counter

    oc = Counter(a["owner"] for a in alerts)
    top = ", ".join(f"{o} ({c})" for o, c in oc.most_common(3))
    spike = sum(1 for t in times if 2 <= t.hour <= 4)
    cc = Counter(a["component"] for a in alerts)
    topc = ", ".join(f"{c} ({n})" for c, n in cc.most_common(3))
    return "\n".join(
        [
            f"alerts: {total}",
            f"recurring: {recurring}",
            f"one-off: {oneoff}",
            f"silenced: {silenced}",
            f"~alerts/day: {per_day}",
            f"2-4am spike count: {spike}",
            f"top owners: {top}",
            f"top components: {topc}",
        ]
    )


def main():
    alerts = json.loads(DATA.read_text())
    digest = build_digest(alerts)
    current_purpose = (
        "Reduce alert noise and protect on-call focus time for BrewBean POS."
    )
    probe_sys = (PROMPTS / "probe_system.txt").read_text()
    probe_user = f"{current_purpose}\n\nAlert feed digest:\n{digest}\n\nFull alert sample (first 10):\n{json.dumps(alerts[:10], indent=2)}"
    print("== Muse Spark Alert Probe ==")
    print(f"model: {MODEL}")
    probe_text = call_muse(probe_sys, probe_user)
    try:
        probe_json = extract_json(probe_text)
    except Exception:
        print("Probe raw:", probe_text[:2000])
        raise
    (STATE / "purpose.json").write_text(
        json.dumps(
            {
                "statement": probe_json.get("refined_purpose", {}).get("statement", ""),
                "rationale": probe_json.get("refined_purpose", {}).get("rationale", ""),
                "version": 1,
            },
            indent=2,
        )
    )
    (STATE / "signals.json").write_text(
        json.dumps(probe_json.get("signals", []), indent=2)
    )
    mem_path = STATE / "memory.jsonl"
    with mem_path.open("w") as mf:
        for p in probe_json.get("patterns", []):
            mf.write(
                json.dumps(
                    {
                        "namespace": "alert_domain",
                        "tier": "semantic",
                        "content": p.get("text"),
                        "source": "probe",
                        "salience": p.get("salience_hint"),
                    }
                )
                + "\n"
            )
    (STATE / "proposals.json").write_text(json.dumps({"probe": probe_json}, indent=2))
    rp = probe_json.get("refined_purpose", {})
    print(f"Refined purpose: {rp.get('statement')}")
    print(f"Rationale: {rp.get('rationale')}")
    print("Patterns:")
    for p in probe_json.get("patterns", []):
        print(f" - {p.get('text')} (salience {p.get('salience_hint')})")
    print("Signals:")
    for s in probe_json.get("signals", []):
        print(
            f" * {s.get('role')} {s.get('direction')} | {s.get('extraction')} [{s.get('unit')}] — {s.get('rationale')}"
        )
    chat_sys = (PROMPTS / "chat_system.txt").read_text()
    patterns_text = "\n".join(
        f"- {p.get('text')} (salience {p.get('salience_hint')})"
        for p in probe_json.get("patterns", [])
    )
    chat_user = f"""Alert feed digest:
{digest}

Extracted patterns:
{patterns_text}

Refined purpose: {rp.get("statement")}

Question: Based on alert patterns above, what is my biggest alert problem and one concrete fix? Answer concisely grounded in numbers, no advice beyond operational propose-only."""
    print("\n== Chat ==")
    chat_text = call_muse(chat_sys, chat_user)
    print(chat_text.strip())
    sa_sys = (PROMPTS / "selfassess_system.txt").read_text()
    purpose_line = f"Current purpose: {rp.get('statement')}"
    signals_lines = "\n".join(
        f"- {s.get('role')} {s.get('extraction')} {s.get('direction')}"
        for s in probe_json.get("signals", [])
    )
    memory_sample = "\n".join(
        f"- {p.get('text')}" for p in probe_json.get("patterns", [])
    )
    sa_user = "\n".join(
        [
            "Mandate: Reduce alert noise for BrewBean POS SRE.",
            purpose_line,
            "",
            "Signal basket:",
            signals_lines or "(none)",
            "",
            "Memory sample:",
            memory_sample or "(none)",
            "",
            "Recent conversation: user asked biggest alert problem; assistant answered grounded in patterns.",
        ]
    )
    print("\n== Self-Assess ==")
    sa_text = call_muse(sa_sys, sa_user)
    try:
        sa_json = extract_json(sa_text)
    except Exception:
        print("Self-assess raw:", sa_text[:2000])
        raise
    (STATE / "assessment.json").write_text(json.dumps(sa_json, indent=2))
    print("Narrative:")
    print(
        textwrap.fill(
            sa_json.get("narrative", ""),
            width=96,
            initial_indent="  ",
            subsequent_indent="  ",
        )
    )
    print("\nProposals:")
    for pr in sa_json.get("proposals", []):
        print(f" - {pr.get('kind')} [{pr.get('risk')}] {pr.get('rationale')}")
        print(f"   payload: {json.dumps(pr.get('payload'))}")
    print(
        "\nState written: state/memory.jsonl state/proposals.json state/purpose.json state/signals.json state/assessment.json"
    )


if __name__ == "__main__":
    main()
