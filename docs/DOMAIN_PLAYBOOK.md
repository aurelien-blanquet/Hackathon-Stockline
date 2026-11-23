# Domain playbook — what our agent must understand on the phone (crèmerie edition)

> General trade knowledge, written before reading our data. **Check every product and rule against our catalog and
> `data/context/` before putting it in the prompt or a scenario.** Stockline's reference is `METIER.md`.

## 1. Cheese & dairy specifics (verify in our catalog)
| What callers say | What it means | Trap for the agent | Where to handle it |
|---|---|---|---|
| « une meule », « une demi-meule », « un quart » | whole wheel / half / quarter (big cheeses: Beaufort, Comté, Abondance) | not a kilo quantity — convert with the product's unit and weight | catalog unit + `speak_fr.say_qty`; ask if the product is sold by kg |
| « à la coupe », « un kilo de Comté » | cut to weight | weight is approximate until preparation (`preparedQty`) | say « environ », the invoice follows the real weight |
| « un Comté dix-huit mois », « Beaufort d'été / d'alpage » | **ageing / grade**, not a quantity | « dix-huit » is not 18 kg | composite tool: search with the full phrase, confirm the variant |
| « Reblochon fermier » vs « laitier » | two different products and prices | the cheaper one is not a valid substitute for a chef who asked fermier | alternatives must respect the client's context (no substitution) |
| « Mont d'Or », « Vacherin » | seasonal cheese (sold roughly autumn to spring) | out-of-season = stock-out with a reason | stock tool + seasonal note in context |
| « des plaquettes », « une motte », « un seau de crème » | butter / cream formats | format = SKU choice | ask « en plaquettes ou en motte ? » when ambiguous |
| « reblo », « tomme », « raclette » | house shortcuts / families | several SKUs behind one word | search → if > 1 candidate, ask which (Jev `pick_product` gives the confidence) |

## 2. Phone traps (any wholesaler)
| Situation | Expected behaviour |
|---|---|
| « comme d'hab », « pareil que mardi » | load the usual basket (`get_client` → usual), propose it in one sentence, ask what changes |
| « cinq… non, quinze kilos » | last value wins; repeat the quantity before writing it (« quinze kilos, c'est bien ça ? ») |
| « cinq » vs « cinquante », « cent » vs « sans » | read back any unusual quantity; compare with the usual basket |
| interruption by someone in the kitchen | ignore what isn't addressed to the agent; never create a line from it |
| client blocked / over credit limit | the ERP only warns (`client_blocked`, `credit_limit`) — the agent must not confirm; courteous, transmit |
| order for a day without a route (`no_route`) | say it and propose the next delivery day |
| complaint | listen, log precisely (`log_client_event`), promise nothing, say who will call back |
| price question | `get_price` for THIS client (negotiated prices win), say it orally (« dix-huit euros cinquante le kilo ») |
| prospect | no order: questions (volumes, days, key products), list prices, propose a call back |

## 3. What makes the agent sound like a pro (METIER « Pourquoi c'est dur »)
- Greets the caller by first name once identified; tutoie if the persona sheet says so.
- Speaks in trade units; never reads ids (`cli_…`, `CMD-…`); numbers through `speak_fr`.
- Proposes the usual instead of asking ten questions.
- Announces a stock-out with a reason and an alternative acceptable for THIS customer.
- Knows the real delivery day; reads the order back before confirming; promises only what the company can keep.

## 4. Prompt to generate more scenarios (Claude Web)
```
Tu écris des scénarios de test pour l'agent vocal d'un grossiste en produits laitiers et fromages (Crèmerie des Aravis).
Voici des fiches clients et le contexte entreprise : <coller 3 fiches de data/context/clients/ + data/context/*.md>
Écris 5 appels au format JSON du fichier scenarios/scenarios.json (id, title, turns = phrases du client, courtes et
orales, avec hésitations ; expect = tools_any / tools_all / tools_none / say_any / say_none).
Couvre : une rupture, un changement d'avis, un nom maison de produit, une question sur la livraison, un client pressé
qui tutoie. Utilise UNIQUEMENT des clients et produits présents dans les fiches fournies.
```
