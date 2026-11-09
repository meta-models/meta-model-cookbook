#!/usr/bin/env bash
# Muse Wonder planner + Muse Ember port-workers. Run from the workspace root.
set -euo pipefail
PKG=$(cd "$(dirname "$0")/.." && pwd)
# Muse Code and its agents get a clean environment (env -i): only the names collected
# here reach them, so other tokens, credentials and proxy settings in your shell stay out. MUSE_NO_AUTO_UPDATE
# and XDG_* pass through when set, so a disabled auto-update and XDG config locations keep working.
[ -f pygments-rs/Cargo.toml ] || { echo "run from the workspace root" >&2; exit 1; }
CLEAN_ENV=(HOME="$HOME" PATH="$PATH" TERM="${TERM:-xterm-256color}" LANG="${LANG:-C.UTF-8}" CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-8}")
# API key users: export MODEL_API_KEY; subscription users: sign in to Muse Code once and leave it unset.
[ -z "${MODEL_API_KEY:-}" ] || CLEAN_ENV+=(META_API_KEY="$MODEL_API_KEY")
for v in MUSE_NO_AUTO_UPDATE $(compgen -e XDG_); do
  [ -z "${!v+x}" ] || CLEAN_ENV+=("$v=${!v}")
done
AGENTS=$PKG/agents/agents.json
exec env -i "${CLEAN_ENV[@]}" \
  muse --model muse-wonder-1.0 --reasoning-effort high --agents "$(cat "$AGENTS")" -c agents.execution_capacity=17 \
  --parallel-tool-calls --sandbox-network restricted --trust-workspace --approval-mode never
