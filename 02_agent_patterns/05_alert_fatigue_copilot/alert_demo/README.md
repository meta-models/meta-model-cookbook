# Alert Demo — sample project for alert fatigue copilot recipe

This is the model's raw output from the recipe run, captured as evidence, not maintained as a product. It analyzes a synthetic BrewBean POS alert feed and runs a probe / chat / self-assess loop against Muse Spark via the Meta Model API.

## Quick start

```bash
export MODEL_API_KEY=...   # your Model API key
pip install openai
./run.sh
```

Expected output shows the refined purpose, 5 patterns, 5 signals, a chat answer grounded in numbers, and a narrative with 8 proposals. See `../artifacts/demo_run.txt` for a captured example.

## Validate

```bash
cd ..
python3 validate_alert_output.py --probe alert_demo/state/purpose.json --assess alert_demo/state/assessment.json
# or full:
python3 validate_alert_output.py --probe artifacts/probe_example.json --assess artifacts/assessment_example.json
```

## Structure

- `demo.py` — Meta Model API Responses call via the OpenAI SDK (`https://api.meta.ai/v1`, model `muse-spark-1.1`)
- `prompts/` — probe, chat, self-assess system prompts
- `data/synthetic_alerts.json` — 42 synthetic alerts .example domains only
- `state/` — written at runtime, gitignored
- `run.sh` — reads `MODEL_API_KEY` (env or `.env`) then runs `demo.py`
