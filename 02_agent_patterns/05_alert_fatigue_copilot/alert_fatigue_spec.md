# Alert fatigue copilot spec

## Loop contract

```
┌────────────────────────────────────────────────────────┐
│              ALERT FATIGUE AGENT LOOP                  │
│  1. RECEIVE — task description + alert feed path       │
│  2. READ — load synthetic_alerts.json, build digest    │
│  3. THINK — reason about patterns vs purpose           │
│  4. ACT — emit STRICT JSON probe result                │
│  5. OBSERVE — write state files, user reviews          │
│  6. CHAT — answer grounded question from memory        │
│  7. SELF-ASSESS — reflect gap, propose self-changes    │
│  8. EVALUATE — done? YES → respond, NO → back to 2     │
│  GUARDS: max 3 turns for demo · token budget ·         │
│          strict JSON parse required · user interrupt   │
└────────────────────────────────────────────────────────┘
```

Loop ends in one of five ways:

| Condition | Meaning |
|---|---|
| final_json_valid | probe and self-assess both returned parseable strict JSON matching schema |
| max_turns | 3 turns reached without valid JSON — abort and show raw |
| token_budget | input + output exceeds the budget — truncate digest and retry |
| parse_fail | JSON extraction fails repeatedly — surface raw model text for manual inspection |
| user_interrupt | Ctrl-C or stop requested |

## Guards table

These are the guards the pattern targets. The shipped `demo.py` implements the load-bearing ones for a single clean run (exactly-once JSON extraction, grounded numbers, propose-only, no PII); the turn cap and token budget are bounds the pattern assumes and that a production harness enforces.

| Guard | How the pattern enforces it |
|---|---|
| Exactly once JSON | client extracts the first balanced `{...}`, rejects if none or unbalanced |
| Grounded numbers | digest pre-computed in Python from the data file, fed to the model as text; the model must cite those numbers, not hallucinate new counts |
| Propose-only | system prompts forbid external actions — only propose changes to self |
| No PII | synthetic data uses `.example` domains only, no real on-call names |
| No advice beyond operational | prompts say "explain only, do not act", "no financial or safety advice" |
| Token budget | digest is ~12 lines, not a full 42-item JSON dump, keeping the prompt small |

## Trace format

Recipe artifacts store transcripts as simplified turn log, mirroring trace_viewer.py pattern from agent_loop_basics:

```
[Turn 1] THINK: I will probe alert feed...
         ACT:   call_muse(probe_system, digest)
         RESULT: JSON with 5 patterns 5 signals
         EVAL: continue to chat
[Turn 2] THINK: answer biggest problem grounded...
         ACT:   call_muse(chat_system, patterns)
         RESULT: text answer citing 66.7% recurring...
         EVAL: continue to self-assess
[Turn 3] THINK: reflect gap vs purpose...
         ACT:   call_muse(selfassess_system, purpose+signals+memory)
         RESULT: JSON narrative + 8 proposals
         EVAL: done
```

See `artifacts/demo_run.txt` for the real captured run.

## State files

| Path | What it is |
|---|---|
| state/purpose.json | current refined purpose statement and rationale, versioned |
| state/signals.json | signal basket array with status proposed |
| state/memory.jsonl | patterns written one JSON per line, namespace alert_domain tier semantic |
| state/proposals.json | probe proposals appended |
| state/assessment.json | self-assess narrative and proposals |

These mirror Forge memory/proposals schema but simplified to flat files for cookbook demo portability.
