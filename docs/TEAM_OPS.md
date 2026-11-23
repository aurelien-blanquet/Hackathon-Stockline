# TEAM OPS — 6 people, 3 pods, 22.5 hours

## 1. Pod matrix (tentative — confirm at 19:15 once the subject is known)

| Pod | People | Owns | Why them | First deliverable (21:30) |
|---|---|---|---|---|
| **A · Voice** `pod_a_voice/` | **Timofey** (lead) + **6th teammate** | STT adapters, mic/phone ingestion, 8 kHz/noise robustness, latency, TTS read-back | Strongest CS/infra → the part most likely to break on real audio | Real audio file → `TranscriptEvent` on the bus with a real provider |
| **B · Agent** `pod_b_agent/` | **Aurélien** (Architect + lead) + **Iyad** | Extraction (LLM + rules), SKU matching, units, history, stock, alerts, ERP injection | Math/modeling + architecture; this is what the jury scores | Stockline catalog loaded; `make eval-llm` runs on their data |
| **C · Product, Demo, Titus, Pitch** `pod_c_ui/` `pitch/` `tests/synthetic/` | **Abel** (lead: console, test runner, run-of-show, timekeeper) + **Mehdi** (Titus interrogator, test cases, pitch voice) | Operator console, synthetic + real test cases, Titus log, deck, demo script | Abel = leadership/adaptability → integration & timekeeping; Mehdi = speed + eloquence → mentors and stage | Titus answers logged in CLAUDE.md §8; console shows a Stockline case end-to-end |

**Architect duties (Aurélien, ~25% of time):** merges to `main`, owns `shared_contracts/` + `app/`, runs every sync, decides in ≤5 min.
**If the subject is outbound calls / multi-turn dialogue:** Pod A grows the dialogue loop (clarification questions via TTS), Pod B exposes `next_question()` from the alerts — the contracts already carry everything needed (`alerts[].suggested_action`, `readback_fr`).
**Missing 6th teammate?** Pod A = Timofey solo on STT, Iyad moves to A at 00:00 if STT is the bottleneck.

---

## 2. Messages

### Message 0 — send NOW (pre-kickoff setup) · FR
```
Salut l'équipe 👋 Hackathon Stockline ce soir 19h. Pour ne perdre AUCUNE minute à 19h30 :
✅ Laptop chargé + chargeur + multiprise si vous en avez une
✅ Python 3.11+, git, VS Code installés ; compte GitHub prêt (envoyez-moi votre pseudo)
✅ Claude Code installé et connecté (sinon Claude Web, ça marche aussi)
✅ Clés API si vous en avez : Anthropic / OpenAI / Deepgram (on centralise ce soir, JAMAIS dans git)
✅ Casque avec micro (tests audio) — et téléchargez 2-3 vocaux WhatsApp de vous qui "commandez" des légumes, ça fera nos premiers tests réels
J'ai préparé le repo de départ (pipeline voix → commande → console qui tourne déjà). Lien : <REPO_URL>
Lisez juste CLAUDE.md (5 min). On se retrouve à l'amphi 18h50.
```
### Message 0 · EN
```
Hey team 👋 Stockline hackathon tonight 7pm. So we lose ZERO minutes at 7:30:
✅ Charged laptop + charger (+ power strip if you have one)
✅ Python 3.11+, git, VS Code; GitHub account ready (send me your handle)
✅ Claude Code installed and logged in (Claude Web is fine too)
✅ Any API keys you have: Anthropic / OpenAI / Deepgram (we pool them tonight, NEVER in git)
✅ Headset with mic — and record 2-3 voice notes of yourself "ordering" vegetables: our first real test audio
Starter repo is ready (voice → order → live console already runs): <REPO_URL>
Just read CLAUDE.md (5 min). See you in the amphi at 6:50pm.
```

### Message 1 — 19:15 (right after the amphi) · FR
```
🚀 C'est parti. Sujet : <1 phrase>. Données : <liste>. Critères : <liste>.
Répondez en 1 ligne MAINTENANT :  prénom · 2 forces techniques · Claude Code ou Claude Web
Pods proposés (on valide à 19:25) :
🅰️ VOIX (pod_a_voice) : Timofey + <6e>
🅱️ AGENT (pod_b_agent) : Aurélien + Iyad
🅲 CONSOLE/DÉMO/TITUS/PITCH (pod_c_ui, pitch) : Abel + Mehdi
Mehdi : tu fonces au Titus à 19:30 avec le script de questions (docs/TEAM_OPS.md §4), retour 20:15 max.
Tout le monde : git clone <REPO_URL> && make setup && make test → screenshot vert dans le chan avant 19:45.
```
### Message 1 · EN
```
🚀 Go. Subject: <1 line>. Data: <list>. Criteria: <list>.
Reply in ONE line NOW: name · 2 technical strengths · Claude Code or Claude Web
Proposed pods (locked at 19:25):
🅰️ VOICE (pod_a_voice): Timofey + <6th>
🅱️ AGENT (pod_b_agent): Aurélien + Iyad
🅲 CONSOLE/DEMO/TITUS/PITCH (pod_c_ui, pitch): Abel + Mehdi
Mehdi: head to Titus at 19:30 with the question script (docs/TEAM_OPS.md §4), back by 20:15.
Everyone: git clone <REPO_URL> && make setup && make test → green screenshot in the channel before 19:45.
```

### Message 2 — 19:30 AI & Git sync protocol · FR
```
📐 RÈGLES DE SYNC (à épingler)
1️⃣ CERVEAU PARTAGÉ : avant chaque session Claude → "Lis CLAUDE.md et docs/CURRENT_STATE.md". Claude Web : collez les 2 fichiers en début de conversation (ou utilisez le Projet Claude partagé).
2️⃣ VOS DOSSIERS SEULEMENT : A → pod_a_voice/ · B → pod_b_agent/ · C → pod_c_ui/, pitch/, tests/synthetic/. Dites-le à Claude : "Tu ne modifies que pod_X/".
3️⃣ CONTRATS GELÉS : shared_contracts/ = interdit. Besoin d'un champ ? Fichier dans docs/contract_proposals/ + ping @Aurélien. Réponse < 15 min.
4️⃣ GIT : branche pod-a / pod-b / pod-c. Commits petits "A: …". Rebase sur main toutes les heures. Merge sur main = make test vert.
5️⃣ ÉTAT : à chaque sync, chaque pod ajoute 6 lignes en haut de docs/CURRENT_STATE.md (template dedans).
6️⃣ CHECKPOINTS : 21:30 · 00:00 · 03:00 → docs/checkpoints/CPn.md (+ lien de partage Claude si dispo). Bloqué > 20 min ? Lisez le dernier CP puis demandez.
7️⃣ INFOS TITUS : toute réponse d'un ingé Stockline → CLAUDE.md §8 dans les 10 min, même incomplète.
⏰ Syncs debout 10 min : 21:30 · 00:00 · 03:00 · 09:00 · 14:00. Retard = on commence sans vous.
```
### Message 2 · EN
```
📐 SYNC RULES (pin this)
1️⃣ SHARED BRAIN: before every Claude session → "Read CLAUDE.md and docs/CURRENT_STATE.md". Claude Web: paste both files at the start (or use the shared Claude Project).
2️⃣ YOUR FOLDERS ONLY: A → pod_a_voice/ · B → pod_b_agent/ · C → pod_c_ui/, pitch/, tests/synthetic/. Tell Claude: "Only modify pod_X/".
3️⃣ FROZEN CONTRACTS: shared_contracts/ is off-limits. Need a field? File in docs/contract_proposals/ + ping @Aurélien. Answer < 15 min.
4️⃣ GIT: branches pod-a / pod-b / pod-c. Small commits "A: …". Rebase on main hourly. Merge to main = make test green.
5️⃣ STATE: at every sync each pod adds 6 lines on top of docs/CURRENT_STATE.md (template inside).
6️⃣ CHECKPOINTS: 21:30 · 00:00 · 03:00 → docs/checkpoints/CPn.md (+ Claude share link if available). Stuck > 20 min? Read the latest CP, then ask.
7️⃣ TITUS INTEL: any Stockline engineer answer → CLAUDE.md §8 within 10 min, even partial.
⏰ 10-min standing syncs: 21:30 · 00:00 · 03:00 · 09:00 · 14:00. Late = we start without you.
```

> **Why checkpoints are files, not just share links:** a shared Claude conversation is a snapshot of one chat;
> it can't carry a Claude Code terminal session, and teammates on Claude Code can't "open" it as context. A committed
> `docs/checkpoints/CPn.md` with the decisive prompt/answer works for every interface. Add the share link as a bonus.

---

## 3. The clock (Mon 19:30 → Tue 18:00)

| Time | Checkpoint | Exit criteria (all must be true) | If missed → |
|---|---|---|---|
| 19:00–19:25 | Kickoff, subject, pods | Message 1 sent, pods confirmed | Architect assigns by default table |
| **19:30** | **Architecture & CLAUDE.md lock** | CLAUDE.md §7 filled from the brief; Stockline data in `data/raw/`; branches created; everyone `make test` green | Nobody codes features until §7 is filled |
| 19:30–20:15 | Titus round 1 (Mehdi) | 7 answers in CLAUDE.md §8 | Abel goes at 20:15 for the rest |
| **21:30** | **First end-to-end dummy pipe + CP1** | A: real audio → TranscriptEvent. B: Stockline catalog + 1 real order through `resolve()`. C: console shows it; 5 real-data test cases added | Cut scope: mock STT stays, B focuses on their data |
| **00:00** | **Core feature freeze + CP2** | `make eval-llm` on their data ≥ rules baseline; all alert types render; ERP payload matches Stockline format | Drop upsell/anomaly polish; protect accuracy |
| 00:30–03:00 | Accuracy grind | Every failure → new test case → fix. Eval number posted each hour | — |
| **03:00** | **Edge-case & audio stress test + CP3** | 10 noisy/8 kHz recordings run; latency p50 posted; known-failures list in CURRENT_STATE | Freeze STT provider choice now |
| 03:30–08:30 | **Sleep rotation** (see below) | — | — |
| **09:00** | **UI polish & integration** | Demo flow rehearsed once end-to-end; ROI numbers from Titus in the deck | Use the backup video path |
| **14:00** | **CODE FREEZE** | `main` tagged `v-demo`; only bugfixes with Architect OK | — |
| 14:00–17:30 | Pitch & live-demo rehearsal | 3 full runs with timer; backup video recorded; Q&A drilled | — |
| **18:00** | **Submission** | Repo link + video + deck submitted by 17:45 (buffer) | — |

**Sleep rotation (non-negotiable — the Wednesday pitch is won by rested speakers):**
- 03:30–06:30 sleep: Mehdi, Abel (pitch + console owners must be fresh at 09:00), + the 6th teammate
- 06:30–09:00 sleep: Aurélien, Iyad, Timofey (Pod B/A lead hand over a written "night shift" list in CURRENT_STATE at 03:30)
- Nobody codes alone on `shared_contracts/` or `app/` while the Architect sleeps.

---

## 4. Titus interrogation script (Mehdi, 19:30) — ask in this order, write answers verbatim

1. **Jury criteria.** « Concrètement, sur quoi on est notés et avec quelle pondération : précision mesurée sur un jeu de test caché, la démo live, la vision produit ? Si vous deviez départager deux équipes ex-aequo, vous regarderiez quoi ? »
2. **Data reality.** « Les audios fournis, ce sont de vrais appels clients (téléphone 8 kHz, bruit) ou des enregistrements propres ? Chaque appel a-t-il la commande réellement saisie en face (vérité terrain) ? On a le numéro appelant / l'identifiant client ? »
3. **Catalog & units.** « Dans vos vraies données, comment passe-t-on de l'unité dite (« deux cagettes », « un bar ») à l'unité facturée ? Vous gérez comment le poids variable (poisson, viande) et les noms maison que chaque client donne aux produits ? »
4. **Failure modes.** « Quelles sont les 3 erreurs que vos clients grossistes vous remontent le plus sur la saisie automatique aujourd'hui ? Laquelle coûte le plus cher ? »
5. **Doubt policy.** « Quand l'agent hésite, vos clients préfèrent qu'il repose la question au restaurateur pendant l'appel, ou qu'il laisse un brouillon au commercial ? Quel taux de commandes validées sans retouche serait « waouh » pour vous ? »
6. **ROI numbers.** « Un grossiste type, c'est combien de commandes par nuit, à quelle heure, combien de minutes de saisie par commande, et combien coûte une erreur (avoir, reprise, client perdu) ? » ← *these numbers go straight into the pitch*
7. **Ship criteria.** « À quoi ressemble une commande injectée dans votre ERP (champs obligatoires, date de livraison, tournée, prix client) ? Et qu'est-ce qui vous ferait dire « on l'intègre lundi » : latence, coût par appel, langues ? »

**Bonus if time:** « Avez-vous un mock d'API ERP / un format JSON cible ? » · « Des clients appellent-ils en arabe, portugais, ou mélangent-ils les langues ? »

**Log template — paste into CLAUDE.md §8 within 10 min:**
```
### 19:45 — Mehdi → <Stockline name, role>
- Q1 criteria: <verbatim answer>
- Q2 data: ...
- ...
- Impact: <what changes> → owner: <pod>
- Surprises / quotes for the pitch: "<exact quote>"
```
