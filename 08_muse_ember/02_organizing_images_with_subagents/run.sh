#!/usr/bin/env bash
# One prompt in Muse Code: Muse Wonder writes the photo pipeline, and 16 Muse Ember subagents run it to caption,
# rename and sort every photo in workspace/Photos/Inbox into albums.
#   ./run.sh              # interactive Muse Code window with the prompt filled in
#   ./run.sh exec         # headless (muse exec)
#   ./run.sh exec <muse args...>   # extra arguments are passed to muse
# Settings (environment):
#   MODEL_API_KEY       required: the pipeline Muse Wonder writes calls the Model API with it
#   MODEL_API_BASE      default https://api.meta.ai/v1
#   EMBER_MODEL         default muse-ember-1.0
#   COORDINATOR_MODEL   default muse-wonder-1.0
set -euo pipefail
cd "$(dirname "$0")"
: "${MODEL_API_KEY:?Set MODEL_API_KEY: the pipeline Muse Wonder writes calls the Model API with it}"
export MODEL_API_BASE="${MODEL_API_BASE:-https://api.meta.ai/v1}"
export EMBER_MODEL="${EMBER_MODEL:-muse-ember-1.0}"
COORDINATOR_MODEL="${COORDINATOR_MODEL:-muse-wonder-1.0}"
[ -d workspace/Photos/Inbox ] || { echo "No photos yet: run python3 prepare/fetch_photos.py first" >&2; exit 1; }

PROMPT='Caption, rename and sort all the photos in Photos/Inbox into albums. First caption a small sample to choose the albums, then write one pipeline script in the workspace that sends 8 photos per muse-ember request at 512 px with minimal reasoning effort, and have 16 muse-ember subagents run it in parallel on their shards. The Model API is OpenAI-compatible: base URL in $MODEL_API_BASE, key in $MODEL_API_KEY, model id in $EMBER_MODEL.'

# A generic worker: it knows nothing about photos. Muse Wonder writes each worker's task.
# The default "general-purpose" subagent gets the same definition, so every worker runs on Muse Ember.
AGENTS=$(python3 - <<'EOF'
import json, os
worker = {
    "description": "A muse-ember worker for one bounded, fully specified task. Give it the complete task: "
                   "the files it owns, the commands to run, and what to report.",
    "model": os.environ["EMBER_MODEL"], "effort": "low", "maxTurns": 20,
    "prompt": "Do exactly the task in your input. Edit only the files it names, run the commands it gives, "
              "fix your own files if a command fails, and report the result in one short line. "
              "Never claim a result you did not run.",
}
print(json.dumps({"ember-worker": worker, "general-purpose": worker}))
EOF
)

FLAGS=(--model "$COORDINATOR_MODEL" --reasoning-effort low
       -c 'agents.execution_capacity=17'            # Muse Wonder + 16 subagents at once (the default allows fewer)
       -c 'run.workflow_trigger_mode="off"'         # spawn the workers directly, no Workflow helper agents
       -c 'provider_retry.base_delay_ms=2000' -c 'provider_retry.retry_after_cap_ms=4000' -c 'provider_retry.max_retries=30'
       --agents "$AGENTS" --parallel-tool-calls
       --yolo)                                      # auto-approve shell commands: use only in this workspace

MODE="${1:-tui}"; [ $# -gt 0 ] && shift
cd workspace
if [ "$MODE" = "exec" ]; then
  muse exec "${FLAGS[@]}" "$@" --disable-reminders "$PROMPT"
else
  exec muse "${FLAGS[@]}" "$@" "$PROMPT"
fi
