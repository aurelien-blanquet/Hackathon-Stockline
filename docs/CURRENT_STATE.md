# CURRENT_STATE — read before you prompt Claude

> Append-only. Newest entry on top. One entry per pod at every sync. Keep each entry under 8 lines.

## Snapshot (Aurélien updates at each sync)
- Phase: kit setup (Docker) · next sync: 21:30 — problem locked + first real call
- Kit on `main`: **not yet** (Aurélien pushes it after `make setup` works — see docs/TEAM_OPS.md §0)
- Providers: mock → real keys after first call · Model: claude-sonnet-5-5 (default)
- Baseline timings: not measured yet
- Blockers: none

---
### [21:45] Voice upgrade — Mehdi (branch `voice-upgrade`, touches Fast + Smart files: please review)
- Done: composite tools `identify_caller`, `find_product`; order edits `update_order_line`, `remove_order_line`, `update_order`, `cancel_order`; spoken recap `say` on every order result; `speak_fr.to_speech()` before TTS; pre-rendered filler on first tool call (+ TTS warm-up); first clause cut at a comma; barge-in keeps only what was heard; colloquial yes / « oui mais » guard; voice prompt rewritten as a call flow; 13 scenarios filled with real Aravis names (s11–s13 new).
- Files: `tools/voice.py` (new), `tools/orders.py`, `agent/prompts.py` (VOICE_RULES + 4 BASE_RULES lines), `agent/guardrails.py`, `agent/speak_fr.py`, `services/voice_session.py`, `scenarios/scenarios.json`.
- Next: run `scenarios/run.py --label "voice upgrade"` with real keys vs `main` (kit) and fill DECISIONS §4.
- Numbers: make test 146 passed · mock smoke 27 turns 0 errors · real-model numbers: not yet

<!-- ENTRY TEMPLATE — copy, fill, put on top
### [HH:MM] Pod Fast|Smart|Natural — <name>
- Done:
- Now:
- Next (≤2h):
- Blocked by / needs from:
- Numbers: scenarios OK x/y · totalMs median/worst
-->
