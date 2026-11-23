# Food-wholesale voice orders — domain playbook (FR B2B)

> Typical values below are **working assumptions for the hackathon**, not industry standards. Replace every
> conversion with Stockline's data at 19:15 and confirm the rest in Titus. "Handled by" = where our code deals with it.

## 1. Context in 5 lines
- Restaurants order **at night for next-morning delivery** (service ends ~23:00, delivery before lunch prep). Calls and
  voice notes pile up; someone retypes them into the ERP before the morning picking — that is the job we automate.
- Callers are busy chefs: short, slangy, interrupted, from a noisy kitchen or a market floor (Rungis).
- They never say SKUs. They say what they always say ("mes tomates", "comme d'hab"), in the unit they think in.
- A wrong line costs a credit note, a re-delivery, or a lost customer. **Precision matters more than recall** — a flagged
  doubt is cheap, a silent error is expensive.
- Stockline's own product: an AI-native ERP for food wholesalers whose agents automate order entry from voice, email and messages. Our demo must look like something they could ship.

## 2. Units (spoken unit → sell unit)
| Spoken | Meaning | Typical conversion (verify!) | Trap | Handled by |
|---|---|---|---|---|
| kilo / kg | weight | 1 | "un kilo et demi" | `normalize.words_to_numbers` |
| colis | supplier case | product-specific (5 kg courgettes, 12 mozzarellas, 40 beurres) | same word, different factor per SKU | `catalog.conversions` |
| cagette | wooden crate (F&L) | 6–7 kg tomatoes | often used interchangeably with *caisse* | conversions |
| caisse / carton | box | product-specific | | conversions |
| plateau | tray | 12 barquettes, 20 avocats, 30 œufs | "un plateau d'œufs" = 1 sell unit | conversions |
| botte | bunch (herbs, radis, poireaux) | 1 | sometimes sold per kg | sell_unit |
| barquette | punnet | 1 | 250 g vs 500 g variants | SKU label |
| pièce / no unit | count | fish/meat: **estimated kg** (bar ≈ 1.2 kg) | final price set at weighing | `WEIGHT_ESTIMATE` alert |
| sac, filet | bag, net | 25 kg potatoes, 5 kg onions | "filet" is also a fish cut! | unit regex needs "filet **de**" |
| palette | pallet | ~1 t | almost always an error or a special deal | `QUANTITY_ANOMALY` |
| "pour 50 balles de…" | money amount | ÷ price | not a quantity | **TODO** (Pod B) |
| "une douzaine", "une dizaine" | 12 / ~10 | exact for eggs/oysters, approx elsewhere | | `words_to_numbers` |
| "deux-trois cagettes" | range | ambiguous | | **TODO**: take max + warn |

## 3. ASR / phonetic traps
| What the ASR writes | What the chef meant | Why | Handled by |
|---|---|---|---|
| barre, bars | **bar** (sea bass) | homophone; also "loup" in the south | phonetic key + alias |
| faut filet | **faux-filet** | homophone | phonetic key |
| lieux jaunes | **lieu jaune** (≠ lieu noir: 2× price) | plural + colour word decides SKU | token coverage scoring |
| cèpes ↔ sept | "sept kilos de cèpes" | number/product homophone | **TODO**: digits before units only |
| sans ↔ cent, vin ↔ vingt | quantities | homophones | STT keyterm boosting |
| daurade / dorade | same fish | spelling variants | alias |
| mozza, burrata | mozzarella di bufala | slang | alias |
| "six heures" | delivery time | matched *beurre* phonetically (real bug found in eval) | times stripped before extraction |
| "huîtres numéro 3", "calibre 57-67", "bar 1-2 kg" | **size/grade**, not quantity | numbers that aren't quantities | **TODO**: calibre regex → line attribute |
| batavia → "bata via" | lettuce | word split | fuzzy token matching |

## 4. Informal habits (what really gets said)
| Utterance | Meaning | Handled by |
|---|---|---|
| « mets-moi comme mardi dernier » | copy the order of last Tuesday | `HISTORY_USED`, `find_history_order` |
| « comme d'hab mais enlève l'huile » | last order minus one line | history + remove |
| « rajoute 2 bottes de basilic en plus » | increment on history line | `increment=True` |
| « trois sacs, euh non pardon, deux » | correction → last value wins | `CORRECTION_RE` |
| « 5 kg de cabillaud… attends Momo… 5 kg de cabillaud » | restatement after interruption ≠ 10 kg | dedupe |
| « 2 caisses de tomates si elles sont belles » | conditional line | `CONDITIONAL_LINE` |
| « c'est combien le cabillaud ? bon mets-m'en 3 kilos » | price question + pronoun | `PRICE_REQUEST`, last mention |
| « des poivrons, deux colis » | product before quantity, unspecified colour | `AMBIGUOUS_SKU` |
| « ce que t'as de beau en poisson blanc » | open request → needs a human/suggestion | **TODO**: `OPEN_REQUEST` alert |
| « le double de d'habitude », « la moitié » | relative quantity | **TODO** (LLM handles better) |
| « livre à la cuisine, pas au resto », « avant 6h » | delivery instruction | **TODO**: `notes` field (minor contract bump) |
| « mets ça sur mon compte » | payment talk | ignore |

## 5. Noise & audio
- **Cold room compressors / kitchen hoods**: steady low-frequency hum — STT handles it; the bigger risk is words cut by a door slam.
- **Market floor (Rungis)**: loudspeakers, forklifts, other voices → crosstalk ("Momo, pose ça") enters the transcript. Our extractor ignores clauses without product/quantity; the LLM is told to.
- **PSTN 8 kHz, compressed WhatsApp voice notes**: test with a downsampled copy of every recording (`ffmpeg -i in.wav -ar 8000 out.wav`).
- **Accents & code-switching** (Maghrebi Arabic, Portuguese, Italian product names): ask Titus Q-bonus; keep `lang` in `TranscriptEvent`.
- **Biggest lever**: bias the STT with catalog vocabulary (OpenAI `prompt`, Deepgram `keyterm`) — already wired in `pod_a_voice/stt.py`.

## 6. Out-of-stock & substitution logic (propose, never decide)
1. Same family and use (bar de ligne → bar d'élevage; mozzarella di bufala → mozzarella vache), in stock.
2. Price gap shown to the operator (the reason string carries the price).
3. Never auto-substitute fish species or meat cuts on a premium menu item — always a `block` alert; the operator calls or the agent asks during the call.
4. Seasonality: in late November, strawberries/gariguette are out → expected `OUT_OF_STOCK` with no substitute ("prévenir le client").
5. Partial stock → `LOW_STOCK` warn with available quantity (ship partial vs wait is the customer's call).

## 7. Prompt for generating more synthetic calls (Claude Web)
```
Tu génères des transcriptions réalistes d'appels nocturnes de restaurateurs à leur grossiste alimentaire (France).
Catalogue (sku | libellé | unité de vente | conditionnements) :
<coller data/catalog_sample.csv ou le catalogue Stockline>
Clients et dernières commandes : <coller data/customers_sample.json>
Génère 15 appels au format JSONL, une ligne par appel :
{"id": "...", "customer_id": "...", "features": [...], "transcript": "...", "expected": [{"sku": "...", "qty": <quantité en unité de vente>}], "alerts": [...]}
Contraintes : style oral (euh, bon, ouais), au moins 1 correction en cours de phrase, 1 interruption (quelqu'un en cuisine),
1 produit hors catalogue (sku null + alerte UNKNOWN_SKU), 1 référence à une commande passée, 1 condition ("si elles sont belles"),
des unités variées (colis, cagette, botte, pièce, kilo), des erreurs de reconnaissance vocale plausibles ("barre" pour bar, "faut filet").
Les quantités attendues doivent être calculées exactement avec les conditionnements. Types d'alertes autorisés :
UNKNOWN_SKU, AMBIGUOUS_SKU, OUT_OF_STOCK, WEIGHT_ESTIMATE, CONDITIONAL_LINE, QUANTITY_ANOMALY, PRICE_REQUEST, HISTORY_USED.
```
Save the output as `tests/synthetic/extra_cases.jsonl` (every `*.jsonl` there is evaluated and appears in the console dropdown) and spot-check 3 cases by hand before trusting the ground truth.
