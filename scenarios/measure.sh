#!/usr/bin/env bash
# Before/after measurement for DECISIONS.md §4, in one command (services must be running: make up).
#   ./scenarios/measure.sh                 # kit d'origine (BASE) then current code (HEAD)
#   BASE=e1f68eb ./scenarios/measure.sh    # choose the "before" commit (default: the raw kit commit)
#   ONLY=head ./scenarios/measure.sh       # skip the baseline, measure the current code only
# The AI service reloads its code live (Docker bind mount / --reload), so we swap apps/ai/app to BASE, measure,
# then put HEAD back — even on Ctrl-C. Needs real keys in .env (ALLOW_MOCK=1 to test the plumbing).
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${BASE:-e1f68eb}"
AI="${AI_URL:-http://localhost:4100}"
APP=apps/ai/app

run_py() {
  if command -v uv >/dev/null 2>&1; then
    uv run --quiet --with websockets python scenarios/run.py "$@"
  else
    python3 -c "import websockets" 2>/dev/null || python3 -m pip install --user --quiet websockets
    python3 scenarios/run.py "$@"
  fi
}

wait_ai() {  # wait for the AI service to come back after a code swap
  sleep 4
  for _ in $(seq 1 60); do curl -fsS "$AI/health" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "AI service did not come back: make logs"; exit 1
}

health="$(curl -fsS "$AI/health" 2>/dev/null)" || { echo "AI service not reachable on $AI — run make up first"; exit 1; }
echo "$health"
if [[ "${ALLOW_MOCK:-0}" != 1 ]] && echo "$health" | grep -q '"llm":{"provider":"mock"'; then
  echo "LLM is still mock: put the real keys in .env (LLM_PROVIDER=anthropic, STT/TTS too), then make restart"; exit 1
fi
git diff --quiet -- "$APP" && git diff --cached --quiet -- "$APP" || { echo "Uncommitted changes in $APP: commit or stash first"; exit 1; }

if [[ "${ONLY:-}" != head ]]; then
  restore() { git checkout -q HEAD -- "$APP"; }
  trap restore EXIT
  # files that exist now but not in BASE must disappear during the baseline run
  git diff --name-only --diff-filter=A "$BASE" HEAD -- "$APP" | while read -r f; do rm -f "$f"; done
  git checkout -q "$BASE" -- "$APP"
  echo "== baseline: $APP @ $BASE"; wait_ai
  run_py --reset-erp --label "kit d'origine ($BASE)" || true
  restore; trap - EXIT
fi

echo "== current: $APP @ $(git rev-parse --short HEAD)"; wait_ai
run_py --reset-erp --label "$(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-40)" || true
echo
echo "Copy the two 'Paste into DECISIONS.md' rows into DECISIONS.md §4, then commit scenarios/results/."
