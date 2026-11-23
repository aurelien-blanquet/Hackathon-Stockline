# CURRENT_STATE — read me before you prompt Claude

> Append-only. Newest entry on top. One entry per pod at every sync (and after any Titus visit or contract change).
> Format is fixed so Claude can parse it. Keep each entry under 8 lines.

## Snapshot (Architect updates at each checkpoint)
- Phase: PRE-KICKOFF · next checkpoint: 19:30 Architecture lock
- Contract: v1.0.0 · Extractor default: rules · STT: mock
- Eval (15 curated cases, rules): line F1 1.00 (tuned on these — not a real accuracy claim) · LLM: not measured yet
- Demo path green? yes (simulate → console → substitution → ERP stub)
- Blockers: none

---
<!-- ENTRY TEMPLATE — copy, fill, put on top
### [HH:MM] Pod X — <name>
- Done: 
- Now: 
- Next (≤2h): 
- Blocked by / needs from Pod Y: 
- Contract impact: none | proposal docs/contract_proposals/...
- Eval delta: (if Pod B) line_f1 a → b
-->
