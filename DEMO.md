# Live demo and 2-minute video script

## Before recording

1. Restore your original `.env` locally; keep it outside Git.
2. Run `make setup` (first time) then `make dev` as directed in SETUP.md.
3. Open http://localhost:5173 and verify the ERP is populated with **Crèmerie des Aravis** data.
4. Open the Voice page and verify the microphone, STT, LLM and TTS adapters. For free tests, configure mock providers according to the supplied README; use live providers for the final demonstration.
5. Choose an active customer and available products from the actual ERP. Use a fresh draft; don't rely on a particular stock quantity.

## Script — approximately 2 minutes

**0:00–0:15 — Problem.** “Crèmerie des Aravis serves mountain restaurants. Telephone orders are common, but staff must manually translate spoken requests into ERP transactions.”

**0:15–0:35 — Identify.** Caller: “Bonjour, c'est le Chalet de la Balme. Je voudrais commander pour ma prochaine livraison.” Show customer lookup and relevant context.

**0:35–0:55 — Order.** Caller: “Il me faut deux reblochons fermiers et une tomme de Savoie. Quel est mon tarif ?” Show product resolution, customer-specific pricing, stock checks and draft creation. Use the units shown in ERP; if ambiguous, let the agent ask.

**0:55–1:15 — Ambiguity.** Caller: “Et comme d'habitude pour le reste.” The agent should look up the customer's usual basket and clarify which items to add. Do not assume the historical basket is current.

**1:15–1:35 — Safety.** Caller: “Attends, ne confirme pas encore.” The draft must remain unconfirmed. Show the ERP status.

**1:35–1:55 — Confirmation.** After the assistant reads the complete draft, caller: “Oui, je confirme cette commande.” Show the confirmed order in the ERP. If there are credit or stock warnings, handle them rather than forcing confirmation.

**1:55–2:00 — Close.** “One phone call. Verified ERP data. Customer approval before finalization.”

## Jury edge cases to rehearse

- “Le reblochon” (farmer vs dairy vs small format): ask which SKU.
- “La même chose que mardi dernier”: retrieve history rather than invent quantities.
- “Non, finalement deux au lieu de quatre”: do not append duplicates; explain editing limitations if needed.
- “Livrez avant sept heures”: do not guarantee without route evidence.
- “Je ne confirme pas”: no confirmation tool should be allowed.
- Customer on credit hold: report the ERP warning and do not promise fulfillment.
