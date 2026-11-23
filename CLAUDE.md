# CLAUDE.md — Team 09, Crèmerie des Aravis · Stockline voice hackathon

> Read this file, then **`AGENTS.md`** (Stockline's guide to the kit), then `docs/CURRENT_STATE.md`, before writing code.
> Claude Web users: paste this file + `docs/CURRENT_STATE.md` + the file you are changing.
> If a request contradicts these rules, **ask before acting**.

## 1. What we are building
The voice agent of the kit (ERP :4000, AI service :4100, web :5173), made **smart, fast and natural** for our company,
**Crèmerie des Aravis**. The jury calls it **live** with scenarios we don't know. Prizes: best agent + relevance of the
problem; special prizes for fastest (end of speech → first sound), cheapest per successful call, most natural, smartest.
Chosen problem: see `DECISIONS.md` §1 (**fill by 21:30**).

## 2. Ground rules from the kit (AGENTS.md — summary, AGENTS.md wins)
- Business rules live in the backend (`apps/backend/app/services/`). The agent acts **only through tools**.
- New capability = backend route if missing + an `@tool` in `apps/ai/app/tools/`, imported in `tools/__init__.py`.
  Tools return small JSON and raise on error. Keep the `x-actor` header (via `ctx.erp`).
- JSON camelCase on the wire, snake_case in Python. Business date = `meta.today` (`GET /api/meta`), never the real date.
- Web UI: components from `apps/web/src/ui/` only; no native `<select>` / `<input type="date">`.
- Never commit `.env` or `data/seed/`. Data is fictional: no real people or companies.
- Leave alone unless you have a precise reason: `clients/`, `services/utterance.py`, `agent/sanitize.py`,
  `schemas/`, `routers/` (FAQ « Où est-ce que je code ? »).

## 3. Who owns what (avoid merge conflicts between 6 Claude sessions)
| Pod | People | Owns (write) | Goal |
|---|---|---|---|
| **Fast** | Timofey + 6th teammate | `apps/ai/app/services/voice_session.py`, `apps/ai/app/clients/` (warm-up only), `apps/web/src/features/assistant/` | first sound < 1.5 s: warm connections, filler, LLM on stable partials, VAD |
| **Smart** | Aurélien + Iyad | `apps/ai/app/tools/`, `apps/ai/app/agent/` (**incl. `prompts.py`: single owner = Aurélien**), `apps/backend/app/services/` + `routers/` | right action every time, fewer model round-trips: caller preload, composite tools, Jev, missing tools |
| **Natural & proof** | Abel + Mehdi | `scenarios/`, `DECISIONS.md`, `data/context/*.md`, `apps/web/src/pages/voice/`, `docs/PITCH_DEMO.md`, `pitch/` | scenarios + measurements, tone per customer, French voice, slides, video |

- Anyone may **append** to `docs/CURRENT_STATE.md` and `DECISIONS.md` §4–5.
- Need a change in someone else's file? Ask in the channel, or write the exact diff in `docs/proposals/<topic>.md`.
- Text for the prompt from Natural → proposal file → Aurélien merges it into `prompts.py`.
- Prompt-cache rule (TECH 4.8): never put a timestamp, id or per-call data at the **start** of the system prompt;
  per-caller data goes **at the end**.

## 4. Workflow
- Branches `fast`, `smart`, `natural`; small commits prefixed `F:`, `S:`, `N:`; rebase on `main` every hour.
- Merge to `main` only if: services start (`make up`), `make test` passes, and `scenarios/run.py` did not lose a scenario.
- **Every change that should make us faster/smarter = one line in `DECISIONS.md` §4 with before/after numbers.**
- Develop with `*_PROVIDER=mock`, measure with real keys (they have caps).
- Found a failure on a call? Add it to `scenarios/scenarios.json` **before** fixing it.

## 5. Commands
```
make up | make down | make restart (after .env) | make logs | make reset (ERP data back to seed)
make chat                                   # agent in the terminal, shows tools + tokens
make test                                   # apps/ai pytest (needs uv)
uv run --with websockets python scenarios/run.py --label "<what changed>"   # replay scenarios, timings table
curl -s localhost:4100/tools | python3 -m json.tool                        # tools the model sees
```
Helpers already in the repo: `apps/ai/app/agent/speak_fr.py` (numbers, prices, quantities, dates → spoken French; tested).

## 6. Company facts (fill from data/ — newest first)
- _TBD at 21:00: product families, top customers, seasonality, delivery days/zones, credit rules, house vocabulary._

## 7. Stockline answers (Titus) — newest first
<!-- ### HH:MM — who → Stockline person · Q · A · Impact → owner -->

## 8. Decisions (short; details in DECISIONS.md) — newest first
- 20:20 Mon — Pivot: build on the kit; our pre-kickoff starter is archived on branch `archive/starter-v0`.
