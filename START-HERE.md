# Start here — Aravis Voice Sales Copilot

This is the original Stockline `voice-erp-kit` with targeted improvements for the X-Forum hackathon. It includes the original React frontend, FastAPI ERP, Python voice agent and fictional Crèmerie des Aravis data.

## Security first
The provided original ZIP contained a `.env` with private provider configuration. This deliverable **does not include it**. Restore `.env` from your original archive locally only, keep it out of Git, and rotate credentials if they have been shared publicly. `.env.example` remains included.

## Run
1. Install Docker and the prerequisites listed in `SETUP.md`.
2. Put the original `.env` into the project root (locally only).
3. In the project root: `make setup`.
4. Start services using `make dev` or the exact command in `SETUP.md`.
5. Open http://localhost:5173, inspect customers/products, then open the Voice page.
6. Run Python tests: `cd apps/ai && pytest -q` (or `uv run pytest -q` if using uv).

## Files to submit
- GitHub repository: this project, **without** `.env` and without private seed data if your competition rules exclude it.
- `DECISIONS.md` — project choices and evidence.
- `PITCH.md` — slide-ready content; export to presentation slides.
- `DEMO.md` — demo/video plan; record a real 2-minute demo yourself.

## What has been tested
86 Python tests pass. Live browser/voice, Docker and actual provider API calls have **not** been run in this environment. Verify them before presenting.
