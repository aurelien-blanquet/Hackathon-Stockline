# DECISIONS.md — Équipe 09 · Crèmerie des Aravis

> Le jury lit ce fichier. On le remplit **au fil de l'eau** : quoi, pourquoi, ce qu'on a essayé et abandonné, les
> mesures. Une ligne par décision, datée. Les chiffres viennent de `scenarios/run.py` et de la page Voix (colonne Perçu).

## 1. Le problème choisi
**Problème :** _(une phrase — à fixer avant 21:30)_

**Qui appelle qui, quand :** _…_

**Ce que ça coûte aujourd'hui :** _(volume d'appels/commandes tiré des données : nb de commandes par nuit, part
« comme d'habitude », ruptures, clients bloqués, réclamations — citer les chiffres de data/)_

**Ce que l'agent change :** _…_

**Pourquoi celui-là et pas un autre :** _(le jury appelle avec ses propres scénarios : on couvre le cas le plus
fréquent du métier et les cas difficiles qui vont avec)_

## 2. Ce que l'agent sait faire (périmètre)
| Situation | Comportement attendu | Scénario |
|---|---|---|
| « Comme d'habitude » | propose le panier habituel, note ce qui change, relit, confirme après « oui » | s01 |
| Rupture | dit la rupture tout de suite + raison + alternative acceptable pour CE client | s02 |
| Client bloqué | courtois, explique, ne confirme rien, transmet | s03 |
| Encours proche du plafond | le dit sans vexer | s04 |
| Jour non livré / trop tard | le dit, propose le prochain jour possible | s05 |
| Changement d'avis | garde la dernière valeur, relit | s06 |
| Réclamation | écoute, note précisément, ne promet rien | s07 |
| Prix / nom maison | retrouve le produit, donne SON prix | s08 |
| Prospect | accueille, questionne, propose un rappel | s09 |
| Question interne de stock | disponible + lots qui finissent + arrivage | s10 |

## 3. Choix techniques
| Heure | Choix | Pourquoi | Alternatives écartées |
|---|---|---|---|
| lun 21:45 | **Outils composites** `identify_caller` (recherche + fiche + panier habituel + encours + tournée / prochaine livraison + commandes en cours + façon de parler) et `find_product` (recherche + stock + prix client + habituel + remplacements) | 1 appel au lieu de 3–4 allers-retours modèle (chacun relit tout le prompt) ; le produit ambigu (« reblo ») est tranché par le panier habituel du client | précharger le client dans le prompt système : casse le cache à chaque appel, et on ne sait pas qui appelle avant qu'il le dise |
| lun 21:45 | **Outils de modification** `update_order_line`, `remove_order_line`, `update_order` (date / consigne), `cancel_order` | les changements d'avis sont un critère du jury (« Naturel ») ; l'ERP savait déjà le faire, l'agent non : il ajoutait des doublons | expliquer à l'appelant qu'on ne peut pas modifier (kit d'origine) |
| lun 21:45 | **Récapitulatif construit par le code** : chaque résultat de commande porte `say` (« quatre reblochons fermiers et quinze kilos de tomme, livraison demain, total … hors taxes ») ; les prix et lignes de `find_product` aussi | le récap entendu = l'état exact de l'ERP ; le modèle ne formate plus de nombres | laisser le modèle formater (erreurs d'arrondi, « 18.5 € ») |
| lun 21:45 | **Français parlé avant TTS** : `speak_fr.to_speech()` sur chaque phrase (prix, €/kg, unités, dates ISO → « demain », heures, %, ids et markdown supprimés, AOP/IGP épelés) | la voix ne lit jamais « dix-huit point cinq euro slash kg » ni un `cli_0012`, quoi que le modèle écrive ; l'écran garde le texte du modèle | se fier au seul prompt |
| lun 21:45 | **Filler pré-synthétisé** au premier appel d'outil si l'agent n'a rien dit (5 phrases en rotation, rendues à l'ouverture de la connexion = chauffe du TTS) | premier son sans attendre ni le modèle ni le TTS ; ne compte jamais comme « premier son utile » dans nos mesures | filler demandé au modèle (aléatoire, coûte un aller-retour TTS) |
| lun 21:45 | **Première proposition coupée à la virgule** (≥ 28 caractères) puis phrases entières | le premier morceau part plus tôt au TTS | couper à chaque virgule : prosodie hachée |
| lun 21:45 | **Barge-in honnête** : l'historique ne garde que les phrases dont l'audio a commencé (« … (interrompu) ») | sinon le modèle croit avoir dit ce que l'appelant n'a jamais entendu (GUIDE-VOIX 5.2) | |
| lun 21:45 | **Garde de confirmation** : oui oraux (« ouais vas-y », « ça marche », « nickel ») acceptés ; « oui mais enlève le beurre » refusé (correction, pas accord) ; `remove_*` traité comme écriture (exécution séquentielle) | ni faux refus sur un vrai oui, ni confirmation sur une correction | |
| lun 21:45 | **Prompt vocal** réécrit en déroulé d'appel (identifier → produits en parallèle → brouillon en une fois → modifier → récap `say` → oui → confirmer) + ton selon `howToTalk` (tutoiement) | moins d'étapes, comportement stable sur les cas du jury | |

## 4. Mesures (avant / après chaque technique)
Méthode : `scenarios/run.py` (tours tapés, mêmes scénarios à chaque fois, médiane + pire cas) ; t0 = fin du tour
(relâchement d'Espace). `sttMs` mesuré à part, au micro, sur la page Voix. On précise si le premier son est un filler.

| Version | llmFirstTokenMs | ttsFirstByteMs | totalMs méd. / pire | outils/tour | scénarios OK |
|---|---|---|---|---|---|
| kit d'origine | | | | | |

| Mesure micro (page Voix) | sttMs méd. | Perçu méd. / pire | Commentaire |
|---|---|---|---|
| kit d'origine | | | |

**Coût par appel réussi :** _(tokens entrée / sortie / cache lus par scénario via `make chat` ou les logs ; prix
fournisseur ; total ÷ scénarios réussis)_

## 5. Ce qui a marché, ce qui n'a pas marché
| Heure | Essai | Résultat | On garde ? |
|---|---|---|---|
| lun 21:45 | Améliorations ci-dessus (§3), branche `voice-upgrade` | `make test` : 146 tests OK (dont 33 nouveaux : `tests/test_voice_upgrade.py`). Fumée de bout en bout (ERP + service IA en mock, 13 scénarios par WS /voice) : 27 tours, 0 erreur, filler entendu et en rotation. **Pas encore mesuré avec un vrai modèle / vraies voix** : le mock LLM ne sait pas suivre une conversation, son score de scénarios ne veut rien dire. | à mesurer avec les clés |

## 6. Limites connues
- _…_
