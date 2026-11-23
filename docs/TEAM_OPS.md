# TEAM OPS — kit edition (6 people, 3 pods, until Tue 18:00)

## 0. Put the kit on `main` (Aurélien, once `make setup` works) — 3 minutes
The repo already holds our team layer (`CLAUDE.md`, `DECISIONS.md`, `docs/`, `scenarios/`, `speak_fr.py`). None of
these files exist in the kit, so the kit drops in without conflicts:
```bash
cd voice-erp-kit                      # the folder from the team zip (contains Makefile, AGENTS.md, data/, .env)
rm -rf .git                           # only if you already ran SETUP step 4 locally (it's a single "start" commit)
git clone https://github.com/aurelien-blanquet/Hackathon-Stockline.git /tmp/hs && mv /tmp/hs/.git . && rm -rf /tmp/hs
git checkout HEAD -- CLAUDE.md DECISIONS.md docs scenarios apps/ai/app/agent/speak_fr.py apps/ai/tests/test_speak_fr.py
git check-ignore .env data/seed       # MUST print both lines — otherwise stop and ask
git add -A && git status --short | grep -E '\.env$|data/seed' && echo "STOP: secret or seed staged" || echo "clean"
git commit -m "Kit voice-erp-kit (team-09 Crèmerie des Aravis) + team layer" && git push origin main
```
Then on GitHub: **Settings → General → Change visibility → Private**, and **Settings → Collaborators** → teammates +
the jury accounts (ask Stockline for the handles). Teammates: `git clone`, then `make setup`. `data/seed/` is in the repo; `.env`
(keys, git-ignored: the repo is **public**) is copied from the unpacked team kit (`~/Downloads/voice-erp-kit`, Desktop,
Documents, home) or its zip if found, else created with mock providers: paste your keys, `make restart`.

## 1. Pods (folder ownership is in CLAUDE.md §3)
| Pod | People | First deliverable (00:00) |
|---|---|---|
| **Fast** | Timofey + 6th | warm connections at call start (TTS ≈ 1.9 s cold → 0.3 s warm) + filler on the first tool call (pre-synthesised) |
| **Smart** | Aurélien + Iyad | caller identified → profile, usual basket, open issues, credit status, persona sheet loaded once at the end of the system prompt; composite `quote_product` |
| **Natural & proof** | Abel + Mehdi | DECISIONS §1 written, 10 scenarios filled with real names, baseline numbers, French ElevenLabs voice chosen |

## 2. Message to send NOW
**FR**
```
🔁 Changement de plan : le sujet = rendre l'agent vocal du kit Stockline smart / fast / natural sur NOTRE entreprise (Crèmerie des Aravis). Le jury l'appelle en live sur des scénarios surprise. Notre ancien starter est archivé.
Pods :
⚡ FAST (latence, voice_session.py, web voix) : Timofey + <6e>
🧠 SMART (outils, prompts, Jev, backend) : Aurélien + Iyad
🗣 NATURAL & PREUVE (scénarios, mesures, DECISIONS.md, voix, pitch) : Abel + Mehdi
Tout le monde : make setup qui marche + un vrai appel sur la page Voix avant 21:30. Puis lisez CLAUDE.md (5 min) — chaque session Claude commence par « lis CLAUDE.md et AGENTS.md ».
Abel/Mehdi : lisez data/context/ + 5 fiches clients, proposez LE problème avant 21:15.
Sync debout 21:30.
```
**EN**
```
🔁 Change of plan: the task = make the Stockline kit's voice agent smart / fast / natural on OUR company (Crèmerie des Aravis). The jury calls it live with surprise scenarios. Our old starter is archived.
Pods:
⚡ FAST (latency, voice_session.py, voice web): Timofey + <6th>
🧠 SMART (tools, prompts, Jev, backend): Aurélien + Iyad
🗣 NATURAL & PROOF (scenarios, measurements, DECISIONS.md, voice, pitch): Abel + Mehdi
Everyone: a working make setup + one real call on the Voix page before 21:30. Then read CLAUDE.md (5 min) — every Claude session starts with "read CLAUDE.md and AGENTS.md".
Abel/Mehdi: read data/context/ + 5 customer sheets, propose THE problem before 21:15.
Standing sync 21:30.
```

## 3. Clock
| Time | Checkpoint | Exit criteria |
|---|---|---|
| **21:30** | Problem locked | DECISIONS §1 filled with numbers from data/; kit on `main`; everyone made one real call; scenarios filled with real names |
| **22:30** | Baseline | `scenarios/run.py --label "kit d'origine"` with real keys → DECISIONS §4; 3 mic calls → sttMs + Perçu |
| **00:00** | Quick wins | warm-up + filler (Fast), caller preload (Smart), French voice + tone per persona (Natural) merged; re-run, row in §4 |
| **03:00** | Smart pass | composite tools, missing write tools (edit/remove line, delivery date, repeat order), Jev yes/no after read-back, prompt trimmed, Haiku vs Sonnet compared on all scenarios |
| 03:30–09:00 | Sleep rotation | 03:30–06:30 Abel, Mehdi, 6th · 06:30–09:00 Aurélien, Iyad, Timofey (hand over a night list in CURRENT_STATE) |
| **09:00** | Natural pass | read-back, spoken numbers via `speak_fr`, interruptions, noisy-room test; VAD only if green, Space stays as fallback |
| **12:00** | Feature freeze | only bug fixes; scenario pass rate and timings final |
| **13:00** | Video | 2-min real call recorded (two takes) |
| **14:00** | Code freeze | fresh clone + `make setup` on a 2nd laptop works; tag `v-demo` |
| 14:00–17:00 | Slides + rehearsal | 5-min deck; teammates play the jury with scenarios the speaker hasn't seen |
| **17:30** | Submit | private repo + jury collaborators, DECISIONS.md, slides, video (deadline 18:00) |

## 4. Questions for the Stockline team (Mehdi) — log answers in CLAUDE.md §7
1. **Démo live** : le jury parle dans notre micro, sur notre laptop, en push-to-talk ? Ou faut-il un mode mains libres ?
2. **« Le plus rapide »** : mesuré comment — colonne Perçu de la page Voix, ou chrono externe ? Un filler (« Je regarde. ») compte-t-il comme premier son ?
3. **« Le moins cher »** : comment calculez-vous le coût d'un appel (LLM + Soniox + ElevenLabs) ? Qu'est-ce qu'un appel « réussi » ?
4. **Scénarios du jury** : surtout des clients qui commandent, ou aussi fournisseurs / transport / interne ? Jouerez-vous les personas de nos fiches clients ?
5. **Plafonds de nos clés** : combien de tokens / minutes avant blocage ? (pour doser nos runs de mesure)
6. **Comptes GitHub du jury** à ajouter en collaborateurs ?
7. **Côté produit** : quel appel vos clients grossistes aimeraient le plus automatiser demain ?
