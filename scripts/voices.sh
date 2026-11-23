#!/usr/bin/env bash
# List the ElevenLabs voices your key can use, French ones first: copy an id into TTS_VOICE in .env, then make restart.
# Uses TTS_API_KEY from .env. A French voice from the ElevenLabs Voice Library must first be added to "My Voices"
# (elevenlabs.io → Voices → Voice Library → filter Language: French → Add) to appear here.
set -euo pipefail
cd "$(dirname "$0")/.."
key="$({ grep -E '^TTS_API_KEY=' .env || true; } | tail -1 | cut -d= -f2- | tr -d '[:space:]"')"
[[ -n "$key" ]] || { echo "No TTS_API_KEY in .env: put your ElevenLabs key there first."; exit 1; }
curl -fsS -H "xi-api-key: $key" "https://api.elevenlabs.io/v1/voices" | python3 -c '
import json, sys
voices = json.load(sys.stdin).get("voices") or []
def french(v):
    labels = " ".join(str(x) for x in (v.get("labels") or {}).values()).lower()
    langs = " ".join(str(l.get("language", "")) for l in v.get("verified_languages") or []).lower()
    return "fr" in langs.split() or "french" in labels or "français" in labels or "fr" in langs
voices.sort(key=lambda v: (not french(v), v.get("name", "")))
print(f"{len(voices)} voices — French first. Put the id in .env: TTS_VOICE=<id>, then make restart\n")
for v in voices:
    labels = ", ".join(f"{k}: {x}" for k, x in (v.get("labels") or {}).items())
    tag = "FR " if french(v) else "   "
    print(tag, v["voice_id"], " ", v.get("name", ""), " (" + labels + ")")
if not any(french(v) for v in voices):
    print("\nNo French voice yet: elevenlabs.io → Voices → Voice Library → Language: French → Add to My Voices, then rerun.")
'
