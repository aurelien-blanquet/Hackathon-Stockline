# Winning demo & pitch — Wednesday 25/11, 15:00, X-Forum (3 min)

## The one sentence the jury must repeat afterwards
**« Le restaurateur parle comme il parle ; à 6 h la commande est dans l'ERP, et le seul travail humain, c'est un clic sur ce qui est vraiment douteux. »**

## 3-minute run-of-show (two speakers: Mehdi = story & ROI, Aurélien = live demo & tech)
| Time | Who | What is on screen | What is said (gist) |
|---|---|---|---|
| 0:00–0:25 | Mehdi | Photo/sound: phone ringing at 23:40, kitchen noise | The problem in one scene: a chef orders between two services, someone retypes it at 4 am. Titus number: **<N> commandes/nuit × <M> min** (Q6). |
| 0:25–1:45 | Aurélien | **Live console** — play a real messy call (noise + correction + "comme mardi dernier" + out-of-stock) | Watch the transcript stream; cart fills; confidence bars; red alert "mozzarella di bufala en rupture → vache disponible". **One click: substituer. One click: valider → ERP.** Then 🔊 read-back to the customer. |
| 1:45–2:05 | Aurélien | Second call, live mic, **someone from the jury says one item** (if allowed) — else Mehdi | Proof it's not scripted. Fallback = pre-recorded clip (see below). |
| 2:05–2:35 | Mehdi | One slide: accuracy table (rules vs Claude, on Stockline's data) + latency | "On <X> real calls: <Y>% orders exact without touching, every error caught as an alert, none silent." Only show measured numbers. |
| 2:35–2:55 | Mehdi | ROI slide | Hours saved / night, errors avoided, upsell captured (the "Commande habituellement X — le proposer ?" alert). |
| 2:55–3:00 | Both | Team slide | "Built in 22 h, plugs into Stockline's ERP format today." |

## ROI formula (fill ONLY with Titus numbers — never invent them on stage)
```
minutes_saved_per_night = orders_per_night × entry_minutes_per_order × auto_rate
    auto_rate = share of orders injected with 0 operator edits (= exact_order_rate from tests/eval.py on real data)
residual_review_minutes = orders_per_night × (1 − auto_rate) × review_seconds_per_flagged_order / 60
errors_avoided_per_month = orders_per_month × baseline_error_rate × share_of_errors_our_alerts_catch
upsell_eur_per_month   = upsell_alerts_shown × acceptance_rate × avg_line_value     ← say "if 1 in 10 is accepted…"
```
Present as: "For a wholesaler like <Titus example>: <A> h/night → <B> min/night."

## Demo-day safety net
- **Network dies:** `EXTRACTOR=rules`, `STT_PROVIDER=mock` + simulate button → everything still works offline (verified).
- **Mic fails:** pre-recorded `.webm` uploaded via the same endpoint; keep a 45-second screen recording of the full flow on the desktop.
- **Laptop dies:** second laptop with repo at tag `v-demo`, `make demo` tested at 17:00 Tuesday and 14:00 Wednesday.
- Zoom browser to 125%, dark room check, sound check of the read-back on the venue speakers.

## Likely jury questions (prepare a 2-sentence answer each)
1. How does it behave on 8 kHz phone audio? → numbers from the 03:00 stress test.
2. What happens when it's wrong? → never silent: block/warn alerts, human-in-the-loop, operator edits are logged.
3. Cost per call? → STT minutes × price + LLM tokens (measure on 10 calls; quote the median).
4. Latency? → p50 STT + extraction, and why it doesn't matter much for night orders (but read-back does).
5. Why not just an LLM end-to-end? → deterministic resolver = auditable conversions, stock and prices never hallucinated.
6. How does it learn a customer's vocabulary? → aliases per customer from validated orders (roadmap; show the alias column).
7. Multi-language / accents? → Titus answer + what we tested.
8. Integration with Stockline? → ERP payload matches their format (Titus Q7).
9. Outbound / dialogue? → read-back + clarification questions generated from alerts (`suggested_action`).
10. What would you build next week? → per-customer alias learning, call-back for blocked alerts, calibre/size parsing.

## Deck (6 slides max, built Tuesday 09:00–13:00 by Pod C)
1. The 23:40 phone call (problem + Titus quote) · 2. Live demo (no slide — the console) · 3. How it works (the 3-pod diagram from CLAUDE.md §2, simplified) · 4. Measured accuracy & latency · 5. ROI · 6. Team + "ready to plug in".
