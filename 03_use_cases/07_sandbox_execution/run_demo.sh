#!/usr/bin/env bash
# One-shot runner: set up a self-contained venv, sanity-check Docker, then let
# Muse Spark fix the bug inside a disposable sandbox. Grading is a separate step
# (see grade.py) because it rebuilds the image and runs the full regression set.
#
#   MODEL_API_KEY=... ./run_demo.sh
set -euo pipefail
cd "$(dirname "$0")"

: "${MODEL_API_KEY:?set MODEL_API_KEY (bearer token for the model endpoint)}"

if [ ! -d .venv ]; then
  echo "creating .venv and installing deps…"
  python3 -m venv .venv
  ./.venv/bin/pip -q install --upgrade pip
  ./.venv/bin/pip -q install -r requirements.txt
fi

./.venv/bin/python - <<'PY'
import subprocess, sys
r = subprocess.run(["docker","version","--format","{{.Server.Version}}"],
                   capture_output=True, text=True)
if r.returncode: sys.exit("Docker is not reachable — start Docker Desktop.")
print("docker server:", r.stdout.strip())
PY

./.venv/bin/python sandbox_scaffold.py "$@"

echo
echo "grade it for real with:  ./.venv/bin/python grade.py"
