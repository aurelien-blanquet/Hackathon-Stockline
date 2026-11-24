# CURRENT_STATE — read before you prompt Claude

> Append-only. Newest entry on top. One entry per pod at every sync. Keep each entry under 8 lines.

## Snapshot (Aurélien updates at each sync)
- Phase: kit setup (Docker) · next sync: 21:30 — problem locked + first real call
- Kit on `main`: **not yet** (Aurélien pushes it after `make setup` works — see docs/TEAM_OPS.md §0)
- Providers: mock → real keys after first call · Model: claude-sonnet-5-5 (default)
- Baseline timings: not measured yet
- Blockers: none

---
### [12:00] /voice human, fast, reliable — Mehdi (touches Fast + Smart files: please review)
- Done: `services/customer_text.py` (CustomerGate: INTERNAL/CUSTOMER split, success claims wait for the ERP);
  late neutral waiting phrase (`VOICE_FILLER_AFTER_S`, `VOICE_FILLERS=0` to disable); voice-only `may_confirm`
  branch bound to the latest recap (`agent/guardrails.py`, chat/command unchanged); `reconcile_interrupted` (no
  duplicate after barge-in); `CachedErp` + prefetch on stable partials; Speaker renders the next sentence ahead;
  `VOICE_TTS_VOICE/MODEL/SETTINGS` + `make voice-samples`; speak_fr thousands / dd/mm / cl. Prompt (Aurélien,
  please review): persona, one question, [notes] channel, blocked / discount wording.
- Next: pick the female voice by ear (`make voice-samples`), run `docs/VOICE_HUMAN_TESTS.md` at the mic.
- Numbers: make test 275 passed · voice_eval ERP checks 7/8 → 8/8 · p95 useful 5.2 s → 4.0 s · LLM/turn 2.11 → 1.95

### [10:30] Voice concise + market in the call — Mehdi (touches Fast + Smart files: please review)
- Done: VOICE_RULES rewritten for 10–25-word turns (Aurélien: `prompts.py` is yours, please review); fillers/acks off
  by default (`VOICE_FILLERS=1` restores them); narration sentences never voiced (`META_TALK`); `fast_path.preload`
  reads quantities and runs the express market (`market/express.source`) for every short product in parallel
  (budget 0.6 s); new WS messages `agent_status` / `agent_offer` (`services/offer.py`: customer-facing only);
  Voix page shows status + offer card instead of tool rows (`pages/voice/offer-card.tsx`).
- Next: measure with Haiku; the model sometimes still writes one sentence before a tool on follow-up turns.
- Numbers: make test 225 passed · web typecheck OK · real key: question/offer turns 20–26 words, preload+market 0.37 s

### [08:00] Market speed — Mehdi (branch `market-speed`, built on Aurélien's `express-market`)
- Morning market: decision in code first (synchronized rounds), purchase orders written at once, narration replays the
  script (never decides). Rapide / Démonstration switch on /market. Fewer model calls (templates + cache), metrics in
  the report line. Buyer no longer names rivals.
- Numbers (real key, same seed): decision 61–185 ms, POs 104–348 ms, dialogues 1.2 s fast / 29.6 s demo, same result
  in every mode. `scripts/market_bench.py`: synchronized ≥ sequential on 20/20 seeds. make test 220 passed.
- Not done (on purpose): Redis / TypeScript negotiators (see the reply in chat): single process, no gain.

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
