#!/usr/bin/env bash
# Why is the voice agent not listening / not speaking? One command, keys never printed.
#
#   make doctor            → diagnose: .env providers and keys, the running AI service, ports, other .env files
#   make doctor FIX=1      → also copy the real keys from another .env (e.g. ~/Downloads/voice-erp-kit/.env) into
#                            this one when this one is on mock, then restart the services
#   make doctor FROM=path/to/.env FIX=1   → that .env as the source of the keys
#
# Symptom → cause: the Voix page "hears" « Bonjour, il vous reste du bar ? » whatever you say = STT_PROVIDER=mock;
# answers without real reasoning = LLM_PROVIDER=mock; no ElevenLabs voice = TTS_PROVIDER=mock (the browser reads).
set -uo pipefail
cd "$(dirname "$0")/.."

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; PROBLEMS=$((PROBLEMS + 1)); }
info() { printf '    %s\n' "$*"; }
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
PROBLEMS=0
val() { { grep -E "^$1=" "${2:-.env}" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*$//; s/^"//; s/"$//'; }
mask() { local v="$1"; [[ -z "$v" ]] && echo "(empty)" || echo "${v:0:4}…${v: -2} (${#v} chars)"; }
is_real_env() {  # a .env with at least one real provider and its key
  local f="$1" k
  for k in LLM STT TTS; do
    local p; p="$(val ${k}_PROVIDER "$f")"
    [[ -n "$p" && "$p" != mock && -n "$(val ${k}_API_KEY "$f")" ]] && return 0
  done
  return 1
}

bold "1. This project's .env ($(pwd)/.env)"
if [[ ! -f .env ]]; then
  bad "no .env: run make setup"
else
  for k in LLM STT TTS; do
    p="$(val ${k}_PROVIDER)"; key="$(val ${k}_API_KEY)"
    case "$k" in LLM) what="the agent (LLM)";; STT) what="speech → text";; TTS) what="the voice (text → speech)";; esac
    if [[ -z "$p" || "$p" == mock ]]; then
      bad "${k}_PROVIDER=${p:-(missing)} → $what is FAKE"
    elif [[ -z "$key" ]]; then
      bad "${k}_PROVIDER=$p but ${k}_API_KEY is empty → $what cannot start"
    else
      ok "${k}_PROVIDER=$p, ${k}_API_KEY=$(mask "$key")"
    fi
  done
  [[ "$(val TTS_PROVIDER)" == elevenlabs && -z "$(val TTS_VOICE)" ]] && info "TTS_VOICE empty: default English voice reading French — pick a French one with: make voices"
  [[ "$(val STT_LANGUAGE)" != fr ]] && bad "STT_LANGUAGE=$(val STT_LANGUAGE) (should be fr)"
fi

bold "2. Other .env files with real keys (your team kit)"
SRC="${FROM:-}"
if [[ -z "$SRC" ]]; then
  for f in ../voice-erp-kit/.env "$HOME/Downloads/voice-erp-kit/.env" "$HOME/Desktop/voice-erp-kit/.env" "$HOME/Documents/voice-erp-kit/.env" "$HOME/voice-erp-kit/.env" \
           $(find "$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" -maxdepth 3 -name .env -not -path "$(pwd)/*" 2>/dev/null); do
    [[ -f "$f" && "$(cd "$(dirname "$f")" && pwd -P)" != "$(pwd -P)" ]] && is_real_env "$f" && { SRC="$f"; break; }
  done
fi
if [[ -n "$SRC" && -f "$SRC" ]]; then
  ok "real keys found in $SRC:"
  for k in LLM STT TTS; do info "${k}_PROVIDER=$(val ${k}_PROVIDER "$SRC") ${k}_API_KEY=$(mask "$(val ${k}_API_KEY "$SRC")")"; done
else
  info "none found in ~/Downloads, ~/Desktop, ~/Documents (or FROM=…). The keys come from the ORIGINAL Stockline team zip"
  info "(its .env, with the keys listed as comments at the bottom) — ask a teammate or the Stockline stand."
fi

bold "3. The running AI service (what the Voix page really uses)"
AI_PORT="$(val AI_PORT)"; AI_PORT="${AI_PORT:-4100}"
health="$(curl -fsS --max-time 3 "http://localhost:$AI_PORT/health" 2>/dev/null || true)"
if [[ -z "$health" ]]; then
  bad "nothing answers on localhost:$AI_PORT: start it with make up (or make setup)"
else
  running="$(printf '%s' "$health" | python3 -c 'import json,sys; h=json.load(sys.stdin); print(" ".join(k + "=" + h[k]["provider"] for k in ("llm","stt","tts")))' 2>/dev/null)"
  if [[ "$running" == *mock* ]]; then bad "running with: $running"; else ok "running with: $running"; fi
  for k in llm stt tts; do
    want="$(val "$(echo $k | tr a-z A-Z)_PROVIDER")"; have="$(printf '%s' "$running" | tr ' ' '\n' | grep "^$k=" | cut -d= -f2)"
    [[ -n "$want" && -n "$have" && "$want" != "$have" ]] && bad "$k: .env says $want but the service runs $have → make restart (it reloads .env)"
  done
fi
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  others="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E ':(4000|4100|5173)->' | grep -v "$(basename "$(pwd)")" || true)"
  [[ -n "$others" ]] && { bad "containers of ANOTHER copy hold the ports (an old voice-erp-kit?):"; info "$others"; info "stop them: cd ~/Downloads/voice-erp-kit && make down   (or: docker stop \$(docker ps -q))"; }
fi

if [[ -n "${FIX:-}" ]]; then
  bold "4. Fix"
  if [[ -n "$SRC" && -f "$SRC" ]]; then
    cp .env ".env.backup.$(date +%H%M%S)"
    n=0
    while IFS= read -r line; do
      key="${line%%=*}"
      [[ "$line" =~ ^(LLM|STT|TTS|JEV)_[A-Z_]+= && -n "${line#*=}" ]] || continue
      if grep -qE "^$key=" .env; then
        python3 - "$key" "$line" <<'PY'
import sys, re
key, line = sys.argv[1], sys.argv[2]
s = open(".env", encoding="utf-8").read()
s = re.sub(rf"^{re.escape(key)}=.*$", lambda m: line, s, count=1, flags=re.M)
open(".env", "w", encoding="utf-8").write(s)
PY
      else
        printf '%s\n' "$line" >> .env
      fi
      n=$((n + 1))
    done < "$SRC"
    grep -qE '^STT_LANGUAGE=' .env && sed -i.bak 's/^STT_LANGUAGE=.*/STT_LANGUAGE=fr/' .env && rm -f .env.bak
    ok "$n provider settings copied from $SRC (old .env saved as .env.backup.*)"
    if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
      make -s restart >/dev/null 2>&1 && ok "services restarted" || bad "restart failed: run make restart"
      info "check again in ~20 s (services restarting): make doctor"
    else
      info "now restart the services: make restart"
    fi
  else
    bad "no .env with real keys to copy from: put the keys in .env by hand (see SETUP.md), or FROM=/path/to/.env"
  fi
elif [[ $PROBLEMS -gt 0 && -n "$SRC" ]]; then
  echo; info "→ to copy the real keys from $SRC and restart: make doctor FIX=1"
fi

echo
[[ $PROBLEMS -eq 0 ]] && bold "All good: real providers configured and running." || bold "$PROBLEMS problem(s) above."
