# Stockline Voice Agent — hackathon starter

Voice order → structured, ERP-ready draft → human validates in one click.

```bash
make setup                 # venv, deps, .env
make test                  # 15 messy French calls → accuracy report
make run                   # http://localhost:8000 → pick a scenario → "Simuler l'appel"
```

Works fully offline (`EXTRACTOR=rules`, `STT_PROVIDER=mock`). Add `ANTHROPIC_API_KEY` + `EXTRACTOR=llm` for Claude
extraction, and `OPENAI_API_KEY`/`DEEPGRAM_API_KEY` + `STT_PROVIDER` for the 🎙 mic button.

| Read first | |
|---|---|
| `CLAUDE.md` | rules every Claude session follows (architecture, folder locks, contracts) |
| `docs/CURRENT_STATE.md` | live status, append-only |
| `docs/TEAM_OPS.md` | pods, messages, clock, Titus script |
| `docs/DOMAIN_PLAYBOOK.md` | French food-wholesale edge cases, mapped to code |
| `docs/PITCH_DEMO.md` | 3-min demo, ROI formula, Q&A |
| `shared_contracts/` | frozen JSON contracts (`schemas.py` + generated JSON Schemas + examples) |

```
app/              bus + FastAPI wiring (Architect)
pod_a_voice/      STT adapters (mock/openai/deepgram), simulate & upload endpoints
pod_b_agent/      normalize → extract (rules | Claude) → match SKU → resolve (units, history, stock, alerts)
pod_c_ui/static/  operator console (vanilla JS, WebSocket)
tests/            synthetic cases generator + eval
data/             SAMPLE catalog & customers — replace with Stockline's data
```

Status of the untested parts: the OpenAI/Deepgram STT adapters and the Claude extractor are written against the
public APIs but were never run (no keys offline). Run `make eval-llm` and one mic test before anything else.
