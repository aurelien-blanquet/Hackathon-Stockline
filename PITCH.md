# 5-minute pitch — slide-ready content

## Slide 1 — Aravis Voice Sales Copilot
**From a chef's spoken request to an accurate ERP order.**
Crèmerie des Aravis: cheese, raclette and charcuterie distribution across Haute-Savoie.

## Slide 2 — The operational problem
- 45% of orders come by telephone (company dataset).
- Customers use shorthand, regional product names and “the usual”.
- Sales staff must manually enter products, units, negotiated prices and delivery dates.
- An error creates waste, missed deliveries or credit risk.

## Slide 3 — Our solution
Voice -> customer and product resolution -> historical preferences -> stock and price -> draft -> spoken recap -> explicit approval -> ERP confirmation.
**A working transaction, not just a transcript.**

## Slide 4 — Technical design and safeguards
- Reuse existing Python agent, FastAPI ERP, React voice UI and provider adapters.
- Retrieve real ERP state instead of fabricating prices or stock.
- Parallelize independent reads; serialize write batches.
- Block confirmation without a recap and explicit customer approval.
- Treat customer notes as data, not instructions.

## Slide 5 — Demonstration and evidence
- Live French customer order with ambiguous cheese SKU.
- ERP draft and customer-specific price lookup.
- “Do not confirm” -> order remains draft.
- Explicit approval -> confirmation.
- Python regression suite: **86 passing tests**. Real speech latency and success rate: report measured values only.

## Slide 6 — Impact and next steps
- Less re-entry and fewer avoidable order errors (expected, not yet measured).
- Faster peak-season customer handling (hypothesis to validate).
- Next: editable draft lines, multilingual accents, more robust confirmation state, live latency instrumentation.
