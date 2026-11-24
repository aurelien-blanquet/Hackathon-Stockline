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
| mar 03:00 | **Réponse réelle < 1 s** : (1) `services/fast_path.py` : « oui c'est bon » après un récap = `confirm_order` en code + phrase modèle, **aucun appel LLM** (même garde-fou que le modèle ; refusé si alerte ERP ou client bloqué) ; (2) préchargement en code (ERP local ~0,1 s, plafonné à 0,5 s) du client et des produits cités, injectés comme des appels d'outils → le modèle répond en **un** appel ; client injecté seulement si son nom a vraiment été dit (« Julien au dépôt » ≠ le client dont un contact s'appelle Julien) ; (3) **réflexion désactivée en vocal** (`thinking: disabled`, `VOICE_THINKING`) : Haiku pensait ~1–1,5 s avant le 1er mot ; (4) le brouillon se crée dans la même réponse que le récap ; (5) cache de prompt écrit à l'ouverture de l'appel et rafraîchi toutes les 4 min | mesuré : réponse sans réflexion 0,49 s vs 2,2 s, à qualité égale sur nos tours (bons client, produit, prix, rupture, ERP correct) | réduire le prompt (mesuré : aucun gain, il est en cache) ; speech-to-speech (pas de clé) |
| mar 01:30 | **Vitesse** : (1) premier son garanti : si rien n'est dit 0,35 s après la transcription, un accusé pré-synthétisé (« D'accord. », « Oui, un instant. ») ; un seul filler par tour ; (2) `identify_caller(products=…)` cherche les produits déjà cités dans le même appel d'outil ; (3) client reconnu par le prénom du contact (« Jean-Marc du Panier Savoyard ») et par une nette avance de score, au lieu de redemander ; (4) connexions LLM / TTS gardées 5 min (httpx les fermait après 5 s, donc à chaque tour) + connexion LLM ouverte dès l'appel ; (5) marge micro 300 → 200 ms ; (6) Haiku conseillé | mesuré : 3 appels modèle en série au 1er tour (identifier, puis produit, puis réponse) ; Sonnet 1,6 s rien que pour le 1er appel d'outil | répondre sans outil (inventerait) ; ack systématique dès la fin de parole (« D'accord » avant chaque réponse rapide sonne faux) |
| mar 00:30 | **`make doctor`** (FIX=1 répare) + bandeau « Mode démo » sur la page Voix + message d'erreur qui nomme la bonne clé (LLM / STT / TTS) | premier test réel : la page « entendait » toujours « Bonjour, il vous reste du bar ? » = STT mock ; le `.env` créé par setup (mock) avait été gardé, les vraies clés étaient dans un autre `.env`. Vérifié : avec `anthropic` + `soniox` + `elevenlabs` configurés, un tour va jusqu'à l'API (401 avec de fausses clés = chemin réel) | |
| lun 23:55 | **Garde-fous de config** : `make setup` crie si un fournisseur est en mock ; `make voices` liste les voix ElevenLabs françaises de la clé | en mock le micro n'est pas transcrit et il n'y a pas de vraie voix : c'est ce qu'on a vécu au premier test | |

## 4. Mesures (avant / après chaque technique)
Méthode : `scenarios/run.py` (tours tapés, mêmes scénarios à chaque fois, médiane + pire cas) ; t0 = fin du tour
(relâchement d'Espace). `sttMs` mesuré à part, au micro, sur la page Voix. On précise si le premier son est un filler.

| Version | llmFirstTokenMs | ttsFirstByteMs | totalMs méd. / pire | outils/tour | scénarios OK |
|---|---|---|---|---|---|
| *Mesure agent seul (mar 01:30, clé Anthropic, prompt vocal réel, ERP Aravis) : début de la réponse texte après la transcription, médiane de 3 premiers tours d'appel. Ne compte ni STT ni TTS.* | | | | | |
| avant (Sonnet, 3 appels modèle) | | | 3 000–4 250 ms | 2 | — |
| après, Sonnet | | | 3 123 ms (méd.) | 1–2 | — |
| **après, Haiku** (`LLM_MODEL=claude-haiku-5-5`) | | | **1 722 ms (méd.)**, 1 313 au mieux | 1–2 | — |
| **fast paths + sans réflexion, Haiku** (8 tours de 3 appels complets, ERP vérifié) | | | **511 ms (méd.)**, p90 1 014, confirmations 32–40 ms | 0–2 | 3/3 commandes justes |
| *Premier son (accusé pré-synthétisé) : ~0,35 s après la transcription. Les chiffres ci-dessus excluent STT (~0,2–0,4 s) et le 1er octet TTS (~0,2 s) : à mesurer au micro, colonne « Perçu ».* | | | | | |
| kit d'origine | | | | | |

**Scénarios complets** (`scenarios/measure.sh`, mar 01:07–01:09, vraies clés, Sonnet, 13 scénarios / 27 tours tapés,
ERP remis à zéro avant chaque scénario ; résultats bruts : `scenarios/results/` sur la branche `smart`). Score recalculé
avec les vérifications corrigées le mar 01:40 (noms des nouveaux outils, « € » prononcé « euros », s01 réécrit car le
client a déjà une commande confirmée, s05 durci). Le 1er son de notre version est **toujours un filler** pré-synthétisé.

| Version | 1er son méd. / pire (filler compris) | fin de génération méd. (`llmTotalMs`) | llmFirstTokenMs méd. | outils/tour | scénarios OK |
|---|---|---|---|---|---|
| kit d'origine (`e1f68eb`) | 4 435 / 8 375 ms | ≈ 4 270 ms | 4 261 ms | 2,22 | 7/13 |
| voice-upgrade (`d5699d5`, avant les commits vitesse de 01:00–03:00) | **1 673 / 2 699 ms** (filler) | ≈ 3 560 ms | 1 672 ms | 1,63 | 5/13 |

**Après les commits vitesse** (`scenarios/measure.sh`, mar 01:39–01:41, Sonnet, mêmes 13 scénarios / 27 tours).
« 1re vraie réponse » = premier texte qui n'est pas un accusé/filler (`firstAnswerMs`) ; « 1er audio utile » =
`usefulAudioMs` du service. Score avec les vérifications de 01:55 (ajout : récap dit deux fois, réflexion à voix haute).

| Version | 1er son méd. / pire | 1re vraie réponse méd. / pire | 1er audio utile méd. / pire | outils/tour | scénarios OK |
|---|---|---|---|---|---|
| kit d'origine (`e1f68eb`) | 5 092 / 8 003 ms | 4 501 / 7 832 ms | — (non instrumenté) | 2,3 | 3/13 |
| `c3402fb` (fast paths, préchargement, sans réflexion), Sonnet | **356 / 379 ms** (accusé) | **1 602 / 6 243 ms** | 2 151 / 6 379 ms | 1,19 | 2/13 |
| confirmation « oui c'est bon » (chemin rapide, sans modèle) | 173–186 ms | 43–48 ms | 173–186 ms | 1 | — |

Lecture : la vitesse est acquise (vraie réponse 2,8× plus tôt, confirmation sans modèle en moins de 0,2 s). Le score
baisse parce que la **forme** se dégrade : sans réflexion, Sonnet écrit son raisonnement dans le texte, qui est
prononcé (7 tours), et le récap part deux fois quand il y a du texte avant ET après un outil (4 tours). Voir §5.

Lecture : le premier son arrive 2,6× plus tôt, mais c'est le filler ; la vraie réponse n'arrive qu'environ 0,7 s plus
tôt que le kit. Les échecs ne sont pas les mêmes : le kit échoue sur les **modifications** (s11 non compris, s04
confirmation refusée, s06/s12 brouillons ou lignes en double que nos vérifications ne détectent pas encore) ; notre
version échoue surtout sur la **longueur** (8 réponses > 280 caractères, dont s01 qui lit les 9 lignes de la commande
et s09 à 730 caractères) et sur une **régression en s05** (voir §5). À remesurer sur `main` après les commits vitesse,
avec la nouvelle colonne « 1re vraie réponse » (`firstAnswerMs`, fillers exclus) que `scenarios/run.py` calcule désormais.

| Mesure micro (page Voix) | sttMs méd. | Perçu méd. / pire | Commentaire |
|---|---|---|---|
| kit d'origine | | | |

**Coût par appel réussi :** _(tokens entrée / sortie / cache lus par scénario via `make chat` ou les logs ; prix
fournisseur ; total ÷ scénarios réussis)_

## 5. Ce qui a marché, ce qui n'a pas marché
| Heure | Essai | Résultat | On garde ? |
|---|---|---|---|
| mar 03:45 | **Diagnostic latence (tâche 1, sans changer le comportement)** : chaque tour mesure le STT par étape (flux prêt, trames en attente, finalize envoyé, texte final, **secours** retranscription), le 1er mot utile, chaque outil, l'audio d'accusé vs l'audio utile (marque `agent_audio_mark` dans le flux) ; la page Voix sépare « 1er son » et « Réponse utile » ; ligne `[timing]` dans les logs ; `make stt-probe` mesure le finalize Soniox en temps réel avec / sans vocabulaire | mesuré ici (Sonnet, clé réelle) : 1er mot utile 0,9–2,5 s après la transcription (médiane 1,06 s), thinking off n'aide pas Sonnet (1,25 s) ; Haiku 0,5 s. Le 1er tour d'un processus rate le préchargement (index produits froid > 0,5 s) → identify_caller lancé par le modèle à +1,35 s. Soniox / ElevenLabs injoignables depuis notre bac à sable : STT à mesurer sur le Mac (`make stt-probe` + ligne STT de la page Voix) | oui |
| mar 03:45 | **Correctif** : `thinking: disabled` renvoyait 400 sur Sonnet 5.5 → `between_tools` pour Sonnet 5.5, rien pour Opus 5.5 (impossible à couper), `disabled` pour Haiku 5.5 | sans ce correctif, chaque tour vocal sous Sonnet échouait sur le `main` précédent | oui |
| lun 21:45 | Améliorations ci-dessus (§3), branche `voice-upgrade` | `make test` : 146 tests OK (dont 33 nouveaux : `tests/test_voice_upgrade.py`). Fumée de bout en bout (ERP + service IA en mock, 13 scénarios par WS /voice) : 27 tours, 0 erreur, filler entendu et en rotation. **Pas encore mesuré avec un vrai modèle / vraies voix** : le mock LLM ne sait pas suivre une conversation, son score de scénarios ne veut rien dire. | à mesurer avec les clés |
| mar 01:40 | Lecture tour par tour des 2 runs réels (kit vs `d5699d5`) | **Mieux** : modifications de commande (s06, s11, s12 éditent la ligne au lieu de doublons), confirmation du 1er coup (s04), s01 voit la commande déjà confirmée, s04 signale « trois fois ton habituel » et l'encours. **Moins bien** : (1) **trop long** pour la voix (s01 ~40 s de parole, s09 730 car., s03 donne téléphone et nom de la comptable) ; (2) **pense à voix haute** entre deux outils (« Le nom est clair : Grand-Bornand. Je poursuis. », « Je crée le brouillon. », « Je m'en occupe ? C'est noté. ») ; (3) **régression s05** : dit « jeudi a priori possible » (jours de livraison lun/mer/ven) et « aucune commande précédente », alors que le kit trouvait la dernière commande (août) et la fermeture jusqu'à mi-décembre ; (4) tutoiement et vouvoiement mélangés (s05) ; (5) s11 : 5 appels d'outils au 1er tour dont un `get_client` redondant (11 s de génération) | à corriger : (1) Smart, prompt + récap résumé au-delà de 3 lignes ; (2) Fast, ne pas voiser le texte émis entre deux appels d'outils ; (3) Smart, `identify_caller` doit renvoyer dernière commande + contexte client (fermeture saisonnière, jours de livraison) |
| mar 01:40 | Vérifications de `scenarios/run.py` | 3/13 annoncé au départ était faux : anciens noms d'outils, « € » non reconnu, s01 écrit pour un client sans commande. Corrigé ; ajout de `firstAnswerMs` (1re vraie réponse, fillers exclus) | oui |
| mar 01:55 | Lecture des 27 tours après les commits vitesse (Sonnet, sans réflexion) | **Réflexion prononcée** (7 tours) : « Il y a déjà une commande confirmée pour demain. Je vérifie son contenu avant d'en créer une autre. », « Vingt kilos, c'est nettement plus que son habituel […], donc je fais répéter avant d'enregistrer. » (parle du client à la 3e personne), « Ce "d'accord" ne me dit pas si c'est bien vingt kilos […] donc je préfère te redemander. », « Vendredi est le 27 novembre, un jour de livraison du client. ». **Récap en double** (s06, s12, s13) : « … Je valide ? Pour récapituler : … Je valide ? » = texte avant l'outil + `say` après. **Toujours long** : s01 relit les 9 lignes (≈ 700 car.), s09 énumère zones et catalogue. **s05 toujours faux** : ignore la fermeture saisonnière (ouvert mi-déc.), « je n'ai pas le détail de ta dernière commande » (`get_client_history` = événements, pas commandes). **s03 tour 2 = pire cas 6,2 s** : client bloqué, l'agent cherche quand même la raclette puis note, 2 étapes modèle avant le 1er mot. Tu/vous mélangés (s05). s02, s08 : bons (prix et rupture via `identify_caller(products=…)`) | priorités : (1) Fast : ne pas voiser le texte d'une étape qui se termine par un appel d'outil (garde l'écran) ; (2) mesurer Haiku et « réflexion courte » contre « sans réflexion » sur ces 13 scénarios ; (3) Smart : prompt « jamais ton raisonnement, 2 phrases, récap résumé au-delà de 3 lignes, tu/vous selon la fiche » ; (4) Smart : `identify_caller` → dernière commande + ouverture/fermeture saisonnière ; client bloqué → aucun outil produit |
| mar 01:55 | `scenarios/run.py` | nouvelles vérifications : récap dit deux fois, réflexion à voix haute (formulations relevées en vrai) ; s02/s08 acceptent `identify_caller(products=…)` | oui |

## 6. Limites connues
- Push-to-talk : l'appelant parle en maintenant Espace ; l'interruption se fait en rappuyant. Pas de détection de voix
  mains libres (VAD) — piste GUIDE-VOIX 4.2.
- Latence, compréhension avec accent / bruit et coût par appel : **pas encore mesurés avec les vraies clés**
  (`scenarios/measure.sh`, page Voix au micro).
- Identification de l'appelant par la parole (« c'est Jean-Marc du Panier Savoyard ») : pas de numéro appelant.
