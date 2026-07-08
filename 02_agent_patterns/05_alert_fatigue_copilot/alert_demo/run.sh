#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Token per cookbook .env.example convention.
if [ -z "${MODEL_API_KEY:-}" ] && [ -f .env ]; then
  export "$(grep -E '^MODEL_API_KEY=' .env | head -n1)"
fi
if [ -z "${MODEL_API_KEY:-}" ]; then
  echo "Set MODEL_API_KEY env var or create a .env with MODEL_API_KEY=..." >&2
  exit 1
fi

mkdir -p state
python3 demo.py "$@"
