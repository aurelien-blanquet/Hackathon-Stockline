# CLAUDE.md — Stockline Voice Agent (Hackathon Stockline × X-Forum)

> **Every Claude session (Code or Web) reads this file + `docs/CURRENT_STATE.md` before writing code.**
> Claude Web users: paste both files at the top of your conversation, or keep them in the shared Claude Project.
> If something here contradicts what the user asks, **ask before acting**.

## 1. Mission (1 line)
A restaurant calls (or leaves a voice message) at night → we produce a **correct, ERP-ready order draft** with
confidence scores and alerts, and a human validates it in a few seconds. Stockline (YC S25) already sells an
AI-native ERP that automates order entry; the jury is their team. **Accuracy on messy French > flashy features.**

## 2. Architecture
```
 audio/phone ─► Pod A  pod_a_voice/  ── TranscriptEvent ──►  Pod B  pod_b_agent/  ── OrderDraft ──►  Pod C  pod_c_ui/
                (STT, streaming,       (bus topic            (extract → match SKU →  (bus topic     (live console,
                 noise, TTS)            "transcript")         convert → stock →       "order")       human override)
                                                              alerts → confidence)  ◄── OperatorAction ──┘
                               app/bus.py = in-process pub/sub + WebSocket /ws fan-out (Architect)
```
- Pod B re-extracts on the **full accumulated transcript** at each *final* chunk (simple, robust; ~30 ms in rules mode).
- Two extractors behind one interface: `extractor_llm.py` (Claude, forced tool call) and `extractor_rules.py`
  (deterministic). **LLM failure ⇒ automatic rules fallback. The demo never dies.**
- `resolver.py` is deterministic: SKU validation, unit conversion, history merge, stock/substitution, anomalies, upsell.

## 3. Folder ownership — LOCKED (Layer 2)
| Path | Owner | Others may |
|---|---|---|
| `pod_a_voice/` | Pod A — Timofey + (6th teammate) | read |
| `pod_b_agent/` | Pod B — Aurélien + Iyad | read |
| `pod_c_ui/`, `pitch/`, `tests/synthetic/` | Pod C — Abel + Mehdi | read |
| `shared_contracts/`, `app/`, `CLAUDE.md` | Architect (Aurélien) | **propose only** |
| `docs/CURRENT_STATE.md`, `docs/checkpoints/` | everyone (append-only) | append |
| `data/` | Pod B (loaders) — raw Stockline files go in `data/raw/` untouched | read |

**Rule for Claude:** never create/modify a file outside the current user's pod paths. If a change elsewhere is
needed, write a proposal in `docs/contract_proposals/<date>-<topic>.md` and stop.

## 4. Contracts (frozen)
- Source of truth: `shared_contracts/schemas.py` (Pydantic v2). JSON Schemas + examples are generated (`make schemas`).
- `CONTRACT_VERSION` = semver. Additive optional field = minor bump; rename/remove = major = **all-hands only**.
- Change protocol: proposal file → Architect OK in channel → one commit `contract: vX.Y.Z <why>` → `make schemas` → ping.
- Unit vocabulary is French trade units (`colis`, `cagette`, `botte`, …). Quantities in `OrderLine.quantity` are
  **always in the product's sell unit**; spoken values are kept in `spoken_quantity/spoken_unit`.

## 5. Coding standards
- Python 3.11+, type hints, `async` for I/O, Pydantic models at every boundary, no global mutable state outside `pipeline.CALLS`.
- No new dependency without Architect OK (add to `requirements.txt` in the same commit).
- Domain words stay French in code and UI (`colis`, `rupture`, `historique`); code identifiers in English.
- Every bug found on a transcript ⇒ add it as a case in `tests/synthetic/generate.py` **before** fixing it.
- `make test` must pass before merging to `main`. Never commit `.env` or API keys.
- Small commits, prefix with pod: `A: deepgram keyterms`, `B: fix demi-colis`, `C: alert sorting`. Rebase on `main` every hour.

## 6. Commands
```
make setup      # venv + deps + .env
make run        # http://localhost:8000 (console) — /docs for OpenAPI
make test       # generate cases + eval (rules)
make eval-llm   # same with Claude (needs ANTHROPIC_API_KEY)
make schemas    # after any contract change
```

## 7. Dataset facts (fill at 19:15 — from Stockline's brief)
- Subject / exact task: _TBD_
- Data provided (audio? transcripts? catalog? order history? ERP API?): _TBD_
- Catalog format → mapping to `data/catalog_sample.csv` columns: _TBD_
- Evaluation criteria + weights: _TBD_
- Hidden test set? Format of expected output: _TBD_

## 8. Titus insights log (Stockline engineers) — newest first
<!-- template:
### HH:MM — <who asked> → <Stockline person>
- Q: ...
- A: ...
- Impact: <what we change> → owner: <pod>
-->

## 9. Decisions log (ADR-lite) — newest first
- 14:30 Mon — Rules extractor kept as permanent fallback + baseline; LLM must beat it on `make eval`.
- 14:30 Mon — Vanilla HTML console (no build step). Browser `speechSynthesis` for read-back TTS in demo.
- 14:30 Mon — In-process bus; no Redis/Kafka.

## 10. Demo-critical paths — do not break after 14:00 Tue
`/api/voice/simulate` → bus → `pod_b_agent.pipeline.on_transcript` → `/ws` → `index.html`; `/api/agent/operator`; `make demo`.
