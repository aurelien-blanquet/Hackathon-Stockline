# Checklist jury — chaque règle de la présentation (amphi de lancement) → ce qui la couvre → comment le vérifier

Légende : ✅ fait et testé hors ligne · 🔶 fait, **à vérifier avec les vraies clés** · ❌ pas fait / à faire par l'équipe.
Scénarios : `scenarios/scenarios.json` (`./scenarios/measure.sh` ou `uv run --with websockets python scenarios/run.py sXX`).

## 1. Les trois critères du jury (« Comment vous êtes jugés »)

| Critère | Règle de la présentation | Ce qui le couvre | Vérifier | État |
|---|---|---|---|---|
| **Intelligent** | La bonne commande dans l'ERP | brouillon créé pendant l'appel avec toutes les lignes ; récap `say` construit depuis l'ERP ; confirmation seulement après un oui à CE récap (garde dans le code, pas seulement le prompt) | s01, s11 ; page Commandes pendant l'appel | 🔶 |
| | Le bon produit | `find_product` : recherche floue + alias (« reblo », « pastille verte ») ; ambigu → le panier habituel tranche, sinon l'agent demande | s08, s13 | 🔶 |
| | Le bon client | `identify_caller` : plusieurs candidats → l'agent demande lequel | s01 ; « c'est le Chalet » (ambigu) | 🔶 |
| | Il n'invente jamais | données uniquement via outils ; prix = prix négocié de l'ERP ; ids/chiffres jamais inventés (prompt) ; pas d'heure d'arrivée promise ; pas d'avoir promis | s07, s05 | 🔶 |
| **Rapide** | Temps avant le premier mot | filler pré-synthétisé au 1er outil (aucun appel TTS) ; 1re proposition coupée à la virgule ; connexions TTS chauffées à l'ouverture | colonne « Perçu » page Voix ; `totalMs` des scénarios | 🔶 |
| | Latence entre deux répliques | outils composites (1 appel au lieu de 3–4 allers-retours modèle) ; outils indépendants en parallèle ; cache de prompt (Anthropic) ; `LLM_MODEL=claude-haiku-5-5` conseillé | `measure.sh` avant/après | 🔶 |
| **Naturel** | Interruptions | rappuyer sur Espace coupe l'agent ; l'historique ne garde que ce qui a été entendu | tests `test_history_pairing` ✅ ; à l'oreille 🔶 | 🔶 |
| | Accents, bruit | STT en flux (Soniox / Deepgram) + vocabulaire de l'entreprise (produits d'abord) ; micro avec réduction de bruit ; 300 ms de marge au relâchement ; quantité douteuse → faire répéter ; rien compris → « Pardon, vous pouvez répéter ? » | page Voix avec bruit de fond | 🔶 |
| | Changements d'avis | `update_order_line` (la nouvelle quantité remplace), `remove_order_line`, `update_order` (date) ; « oui mais… » ne confirme pas | s06, s11, s12 | 🔶 |
| **Cas d'usage** | Bien choisi et bien justifié | `DECISIONS.md` §1 : pour qui, ce que ça coûte (chiffres de `data/`), pourquoi la voix | relire §1 | ✅ (à valider par l'équipe) |

## 2. Les cinq difficultés (« Les difficultés que vous allez rencontrer »)

| Difficulté | Exemple de la présentation | Couvert par | État |
|---|---|---|---|
| **Comprendre** | bruit, accents, jargon, surnoms, « comme d'hab » | vocabulaire STT (340 noms et alias) ; alias dans la recherche ; jargon dans le contexte entreprise (« une raclette » = meule 6 kg) ; « comme d'habitude » → panier habituel | 🔶 |
| **Converser** | interruptions, changements d'avis, silences gênants | barge-in ; outils de modification ; filler pendant les outils ; reprompt parlé si rien n'est entendu ; une question à la fois | 🔶 |
| **Aller vite** | latence, ERP mis à jour pendant l'appel | filler, composites, parallèle, cache ; chaque écriture apparaît en direct (page Activité, flash violet) | 🔶 |
| **Trouver la bonne info** | bon client, bon produit, historique au bon moment | `identify_caller` charge d'un coup encours, client bloqué, réclamations ouvertes, notes, commandes en cours, façon de parler | 🔶 |
| **Ne pas se tromper** | une erreur coûte cher, ne jamais inventer | garde de confirmation dans le code ; écritures exécutées en séquence ; récap issu de l'ERP ; alertes ERP (bloqué, encours, stock) relayées | ✅ tests · 🔶 en appel |

## 3. Le défi : justifier le cas d'usage

| Question | Où | État |
|---|---|---|
| Pour qui ? (qui s'en sert, à quel moment) | `DECISIONS.md` §1 « Pour qui, quand » | ✅ |
| Qu'est-ce que ça rapporte ? (temps, erreurs, ventes) | §1 « Ce que ça coûte » + « Ce que l'agent change » ; **ajouter les chiffres mesurés** (§4) | 🔶 |
| Pourquoi la voix ? | §1 « Pourquoi la voix » | ✅ |

## 4. Les quatre livrables (rendu **mardi 17h30**, sans exception)

| Livrable | Exigence | État |
|---|---|---|
| Repo GitHub | le code, **lançable depuis le README** : `git clone` → `make setup` (données incluses ; `.env` copié du kit s'il est trouvé, sinon mock + avertissement) | ✅ (tester sur une machine vierge) |
| `DECISIONS.md` | cas d'usage et pourquoi, puis choix techniques | §1 ✅ · §3 ✅ · **§4 mesures ❌** (lancer `./scenarios/measure.sh` avec les clés) |
| Slides | problème choisi, approche, résultats | ❌ (base : `PITCH.md`, `docs/PITCH_DEMO.md`) |
| Vidéo | démo courte, en secours si le live plante | ❌ (script : `DEMO.md`) |

## 5. Avant le passage devant le jury
1. `.env` avec les vraies clés ; `make setup` ne doit afficher **aucun** avertissement MOCK.
2. `TTS_VOICE` = une voix **française** (`make voices`), `LLM_MODEL=claude-haiku-5-5` (plus rapide).
3. `./scenarios/measure.sh` → coller le tableau dans `DECISIONS.md` §4.
4. Trois appels à voix haute sur la page Voix, avec du bruit : commande + changement d'avis + confirmation.
5. `make reset` juste avant la démo (données ERP propres).
