"""Regenerate JSON Schemas + example payloads from shared_contracts/schemas.py (`make schemas`).
JSON Schemas are for non-Python consumers (UI, Claude Web sessions). Never hand-edit them."""
import asyncio, json
from datetime import date
from pathlib import Path
from shared_contracts import schemas as s

ROOT = Path(__file__).resolve().parents[1] / "shared_contracts"
for name in ["TranscriptEvent", "OrderDraft", "OperatorAction", "DashboardEvent"]:
    (ROOT / "json_schema" / f"{name}.schema.json").write_text(
        json.dumps(getattr(s, name).model_json_schema(), indent=2, ensure_ascii=False), encoding="utf-8")

from pod_b_agent.pipeline import extract_order  # noqa: E402
ev = s.TranscriptEvent(call_id="demo-001", seq=3, text="Deux bars de ligne entiers et trois colis de mozza di bufala.",
                       confidence=0.91, customer_id="C001", caller_number="+33612345678",
                       audio=s.AudioMeta(source="telephony", provider="deepgram", sample_rate_hz=8000, stt_latency_ms=240))
draft = asyncio.run(extract_order(ev.text, "demo-001", "C001", date(2026, 11, 23)))
act = s.OperatorAction(call_id="demo-001", action="accept_substitution", line_id=draft.lines[-1].line_id)
for n, m in [("transcript_event", ev), ("order_draft", draft), ("operator_action", act)]:
    (ROOT / "examples" / f"{n}.json").write_text(m.model_dump_json(indent=2), encoding="utf-8")
print("schemas + examples written, contract", s.CONTRACT_VERSION)
