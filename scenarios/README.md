# Scenarios

`scenarios.json` = scripted calls (templates: fill the `{PLACEHOLDERS}` with real names from `data/context/` and the
ERP; `fill` says what to look for). `run.py` replays them over the kit's `WS /voice` and records timings, tools and
checks. Results land in `scenarios/results/` (commit them: they are our evidence for DECISIONS.md).

```bash
uv run --with websockets python scenarios/run.py --label "kit d'origine"
uv run --with websockets python scenarios/run.py s02 s03 --reset-erp --label "filler"
```
Typed turns skip STT (`sttMs` ≈ 0): measure STT and Perçu with the mic on the Voix page.
