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
| | | | |

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
| | | | |

## 6. Limites connues
- _…_
