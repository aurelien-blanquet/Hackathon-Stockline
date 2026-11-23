# DECISIONS — Aravis Voice Sales Copilot

## Problem and business justification

**Company:** Crèmerie des Aravis, a Haute-Savoie cheese, raclette, charcuterie and dairy wholesaler serving mountain resorts and restaurants. The provided company pack reports 95 customers, 59 active products, and 45% of orders arriving by telephone. During the winter rush, sales staff must recognize colloquial cheese names, customer-specific usual baskets, packaging units, agreed prices and delivery constraints, then enter orders manually.

**Chosen user:** an existing restaurant or hotel customer calling to reorder or amend a delivery. **Chosen workflow:** identify caller -> resolve requested products -> load usual basket and preferences -> check inventory and negotiated pricing -> create draft -> read back -> obtain explicit confirmation -> confirm in ERP. This is more valuable than a general-purpose chatbot because the output is a correct operational transaction.

**Why voice:** chefs and shop managers often call while working, not at a computer. The provided data says telephone accounts for 45% of orders. The voice interface allows a spoken order while preserving a verifiable ERP record.

## Architecture

Existing React voice interface -> STT -> Python agent loop -> ERP tool registry -> FastAPI ERP -> agent response -> TTS. Existing voice/LLM adapters remain configurable. The starter's real ERP API remains the source of truth for stock, customer-specific prices, credit and order validation. No prices or inventory numbers are invented by the agent.

## Improvements implemented

1. **Domain-specific prompting:** the assistant is instructed to use the *actual company*, not generic fish-market examples, and resolve "as usual" via the customer record.
2. **Transactional safety:** `confirm_order` is blocked at the agent execution boundary unless the last user utterance explicitly approves an earlier assistant order recap. In single-turn command mode, an explicit order-confirmation imperative is required.
3. **Write ordering:** if a model emits a batch containing writes, the agent executes that batch sequentially rather than concurrently, avoiding order-line races. Read-only batches remain concurrent.
4. **No fabricated delivery promises:** check actual route rules before making delivery-time promises; explain tool limitations rather than claiming a correction was applied.
5. **Regression tests:** confirmation gating, mutation classification, and existing integration tests.

## Tradeoffs and known limitations

- The confirmation guard is deliberately conservative and language-pattern based. It can reject some legitimate colloquial approvals, which the agent can resolve by asking again. It is not a cryptographic or authenticated approval mechanism.
- Existing order tools expose adding lines but no dedicated editing/removing tool; the agent must not pretend it has replaced an existing line. A next iteration should implement edit/remove with tests and backend permission checks.
- Existing push-to-talk UI and configured providers are preserved. Streaming latency and speech naturalness depend on the local machine, provider keys, network and microphone. No live speech performance is claimed without measurement.
- A model may still produce errors or misleading statements. The ERP backend and live human oversight remain necessary.
- The original `.env` is deliberately excluded from the deliverable because it contains private credentials. Copy it locally from the supplied original kit and never commit it.

## Verification

`cd apps/ai && pytest -q` -> **86 passed** in the supplied test environment (2026-11-23). This verifies Python tests, **not** a real end-to-end microphone/LLM/ERP call. Live testing is still required.

## Live metrics to record (fill after real tests)

| Scenario | Correct ERP state? | Time speech end -> first audio | Cost | Notes |
|---|---|---|---|---|
| Known customer, simple reorder | TBD | TBD | TBD | |
| "Comme d'habitude" | TBD | TBD | TBD | |
| Ambiguous cheese name | TBD | TBD | TBD | |
| Insufficient stock | TBD | TBD | TBD | |
| Blocked customer / overdue balance | TBD | TBD | TBD | |
| Customer changes mind | TBD | TBD | TBD | |
| No confirmation | TBD | TBD | TBD | |

## Rejected approaches

- **Blindly auto-confirming orders:** rejected because wrong product, unit or delivery date creates real losses.
- **Hardcoding prices and inventory into prompts:** rejected because the ERP changes and customer-specific pricing matters.
- **Replacing the entire provided voice stack:** rejected because it increases integration risk during a 24-hour event.
