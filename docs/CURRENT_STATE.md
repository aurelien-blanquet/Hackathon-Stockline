# CURRENT_STATE — read before you prompt Claude

> Append-only. Newest entry on top. One entry per pod at every sync. Keep each entry under 8 lines.

## Snapshot (Aurélien updates at each sync)
- Phase: kit setup (Docker) · next sync: 21:30 — problem locked + first real call
- Kit on `main`: **not yet** (Aurélien pushes it after `make setup` works — see docs/TEAM_OPS.md §0)
- Providers: mock → real keys after first call · Model: claude-sonnet-5-5 (default)
- Baseline timings: not measured yet
- Blockers: none

---
### [06:30] « Le marché du matin » — Mehdi (branch `market-floor`)
- Done: central buying agent + one agent per supplier, all calls concurrent; need = last Christmas week's sales − stock
  (`GET /api/purchase-orders/needs`); offers / counters / decision in code (`apps/ai/app/market/strategy.py`), voices by
  Haiku in each supplier's style; purchase orders created in the ERP; page **/market** (tiles, offer board, swimlanes,
  click a tile to listen). API: `POST /ai/market/rounds`, `GET /ai/market/rounds/latest`, SSE `/ai/market/rounds/{id}/events`.
- Demo: Achats & stock → « Marché du matin » → « Lancer le marché » (~37 s). `make reset` before a demo resets the ERP.
- Next: a juror plays one supplier by voice; trigger from a customer call (« je vous rappelle dans deux minutes »).
- Numbers: make test 198 passed · web 16/16 · real run: 9 calls in parallel, 8–9 POs, ~3 % negotiated, ~37 s

### [03:45] Latency diagnosis — Mehdi (branch `latency-diagnosis`; touches Fast files: voice_session, utterance, web assistant)
- Done: per-turn STT breakdown (stream ready, backlog, finalize sent, final, fallback flag), useful-text / tool / ack-audio /
  useful-audio timings, `agent_audio_mark` so the browser measures when the REAL answer is heard; Voix page: « 1er son » vs
  « Réponse utile » + « Transcrit » + a breakdown line per turn; `[timing]` log line; `make stt-probe` (Soniox finalize).
- Fix: Sonnet 5.5 rejects `thinking: disabled` (400) → `between_tools`. Your `main` voice turns on Sonnet were broken.
- Next: on the Mac, one call + `make stt-probe`, paste the STT lines → decide the STT fix with numbers.
- Numbers: make test 184 passed · web 13/13 · Sonnet useful text median 1.06 s after transcript (Haiku 0.5 s)

### [23:55] Voice quality — Mehdi (branch `voice-quality`; touches Fast files: web mic, vocabulary, voice_session)
- Done: mic keeps 300 ms after Space release (last word was cut) + opens when the page is ready if already allowed; STT
  vocabulary = products first (Deepgram keeps 50 terms: it had only client names); « Pardon, vous pouvez répéter ? »
  spoken when nothing is heard; `make setup` warns on MOCK providers; `make voices` lists French ElevenLabs voices.
- Docs: DECISIONS §1 (problem, with data figures) proposed — validate as a team; `docs/JURY_CHECKLIST.md` maps every
  rule of the kickoff slides to what covers it and how to check it.
- Next: real keys + French TTS_VOICE, `./scenarios/measure.sh`, DECISIONS §4; slides + video still to do.
- Numbers: make test 147 passed · web typecheck OK · real-key numbers: not yet

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
