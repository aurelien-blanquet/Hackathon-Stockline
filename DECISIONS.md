# DECISIONS.md — Équipe 09 · Crèmerie des Aravis

> Le jury lit ce fichier. On le remplit **au fil de l'eau** : quoi, pourquoi, ce qu'on a essayé et abandonné, les
> mesures. Une ligne par décision, datée. Les chiffres viennent de `scenarios/run.py` et de la page Voix (colonne Perçu).

## 1. Le problème choisi
> Proposition (Mehdi, lun. soir) à valider par l'équipe. Chiffres tirés de `data/` (3 ans d'historique).

**Problème :** les clients de la Crèmerie des Aravis (restaurants de station, hôtels, supérettes) passent la moitié de
leurs commandes **au téléphone**, et chaque appel est ressaisi à la main dans l'ERP par un commercial, qui n'est pas
toujours disponible quand le client appelle.

**Pour qui, quand :** le chef ou le gérant qui appelle **après son service** (14 h) ou **le soir**, jusqu'à la clôture
de 17 h pour le lendemain (Chablais : 15 h la veille). Le standard ouvre à 7 h et **il n'y a pas de standard de nuit** :
les messages du soir attendent le matin (`data/context/02-journee-type.md`). Les 3 commerciaux (Mathieu, Léa, Romain)
prennent les commandes de leur portefeuille en journée.

**Ce que ça coûte aujourd'hui :**
- 48 % des commandes arrivent par téléphone (10 828 sur 22 612), 9 commandes téléphone par jour en médiane, 7 lignes par
  commande : chaque appel = 7 produits, quantités et unités à ressaisir.
- Le métier est plein de surnoms et de pièges : « une raclette » = une meule de 6 kg, « reblo » = fermier ou laitier,
  « pastille verte / rouge », « comme d'habitude » (contexte entreprise, 340 noms et alias dans l'ERP).
- 653 problèmes qualité et 281 retards de paiement dans l'historique client : il faut savoir à qui on parle (client
  bloqué, encours, réclamation ouverte) avant de promettre.

**Ce que l'agent change :** il répond à l'appel, reconnaît le client et son panier habituel, comprend les noms maison,
vérifie stock et prix négociés, crée la commande dans l'ERP pendant l'appel, la relit et ne la confirme qu'après un
« oui » explicite. Le commercial retrouve une commande déjà saisie (activité visible dans l'ERP), au lieu d'une note.

**Pourquoi la voix :** le client est en cuisine ou derrière son comptoir, les mains prises ; il appelle déjà — c'est
son canal n° 1. Un formulaire ou un portail (5 % des commandes) ne change pas ses habitudes ; l'agent, si.

**Pourquoi celui-là et pas un autre :** c'est le flux le plus fréquent du métier (la prise de commande), et il contient
toutes les difficultés que le jury teste : client ambigu, surnoms, rupture, client bloqué, changement d'avis,
interruption, confirmation. Ce qui est fait et comment on le vérifie : [`docs/JURY_CHECKLIST.md`](docs/JURY_CHECKLIST.md).

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
| lun 23:55 | **Micro** : 300 ms d'enregistrement après le relâchement d'Espace ; micro ouvert dès que la page est prête si déjà autorisé ; mono | le dernier mot (souvent la quantité ou le produit) était coupé ; le premier mot du premier tour aussi. « Perçu » compte depuis le relâchement (honnête : inclut les 300 ms) | pré-enregistrement circulaire (WebM ne se découpe pas proprement) |
| lun 23:55 | **Vocabulaire STT** : l'alias principal de chaque produit d'abord, puis noms courts, mots du métier (meule, barquette, fermier, laitier…), autres alias, clients | Deepgram ne garde que 50 termes : avant, c'étaient 50 noms de clients et aucun produit. Le client dit son nom une fois, les produits tout l'appel | noms complets du catalogue (« … (450 g) ») : jamais prononcés ainsi |
| lun 23:55 | **Rien entendu → l'agent le dit** (« Pardon, je n'ai pas bien entendu… ») au lieu d'un message d'erreur à l'écran | « silences gênants » (présentation, difficulté « Converser ») | |
| mar 00:30 | **`make doctor`** (FIX=1 répare) + bandeau « Mode démo » sur la page Voix + message d'erreur qui nomme la bonne clé (LLM / STT / TTS) | premier test réel : la page « entendait » toujours « Bonjour, il vous reste du bar ? » = STT mock ; le `.env` créé par setup (mock) avait été gardé, les vraies clés étaient dans un autre `.env`. Vérifié : avec `anthropic` + `soniox` + `elevenlabs` configurés, un tour va jusqu'à l'API (401 avec de fausses clés = chemin réel) | |
| lun 23:55 | **Garde-fous de config** : `make setup` crie si un fournisseur est en mock ; `make voices` liste les voix ElevenLabs françaises de la clé | en mock le micro n'est pas transcrit et il n'y a pas de vraie voix : c'est ce qu'on a vécu au premier test | |

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
- Push-to-talk : l'appelant parle en maintenant Espace ; l'interruption se fait en rappuyant. Pas de détection de voix
  mains libres (VAD) — piste GUIDE-VOIX 4.2.
- Latence, compréhension avec accent / bruit et coût par appel : **pas encore mesurés avec les vraies clés**
  (`scenarios/measure.sh`, page Voix au micro).
- Identification de l'appelant par la parole (« c'est Jean-Marc du Panier Savoyard ») : pas de numéro appelant.
