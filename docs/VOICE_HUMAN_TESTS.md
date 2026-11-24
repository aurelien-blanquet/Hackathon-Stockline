# /voice — tests au micro (validation humaine)

`scenarios/voice_eval.py` mesure l'agent en texte (sans micro ni haut-parleur). Ce qui suit ne se vérifie qu'à
l'oreille, sur la page **Voix** (http://localhost:5173), avec les vraies clés (Soniox + ElevenLabs).

Avant : `make restart`, ouvrir la page Voix, attendre « prêt » (les voix d'attente sont pré-rendues à l'ouverture).
Pour chaque test : noter **Perçu** (chip de latence : fin de parole → 1er son utile), ce qui a été entendu, et OK / KO.

| # | Dire (push-to-talk) | Attendu à l'oreille | Échec si |
|---|---|---|---|
| H1 | « Vous avez du reblochon ? » | « Le fermier ou le laitier… ? » en < 1,5 s, voix féminine | un « Oui, un instant », une phrase de recherche, une voix masculine |
| H2 | « C'est le Panier Savoyard du Grand-Bornand, quatre kilos de tomme. » | récap court + « Je valide ? » | « je vérifie », « le client », un identifiant, deux questions |
| H3 | Pendant le récap de H2, couper : « Non attends, six kilos. » | l'audio s'arrête net ; nouveau récap à six kilos ; **une seule** commande dans l'ERP | l'ancien récap reprend, deux commandes |
| H4 | « Mets-moi cinq kilos de tomme… non attends, plutôt trois. » | trois kilos, jamais cinq ni huit | |
| H5 | Après un récap : « Tu as aussi du beaufort ? » puis « Oui. » | **rien n'est confirmé** ; elle redemande | « c'est validé » |
| H6 | Après un récap : « Oui c'est bon. » | « Parfait, c'est validé… » en < 0,3 s | délai, confirmation sans récap |
| H7 | Client bloqué : « C'est La Grolle des Gets, vingt kilos de raclette. » | une phrase de tact, propose (sans promettre) un rappel de la compta | une commande, un rappel promis |
| H8 | « Fais-moi vingt pour cent. » | son tarif, pas de remise inventée, personne d'autre cité | « je vois avec… », une remise |
| H9 | Lecture : demander un prix au kilo et une date | « quatorze euros cinquante le kilo », « jeudi vingt-six novembre » | chiffres lus « un virgule… », dates « 26/11 » |
| H10 | Couper l'agent au milieu d'une phrase, se taire | silence immédiat (< 300 ms) | l'audio continue |
| H11 | Question longue à répondre (marché express : 2 000 reblochons fermiers) | une seule phrase d'attente neutre (« Alors, voyons… ») si ça dépasse ~1,1 s, jamais deux tours de suite | « Oui », plusieurs phrases d'attente |
| H12 | Noms : demander du persillé, du chevrotin, de l'abondance, livrés à Morzine / La Clusaz | prononciation naturelle | à noter pour le dictionnaire |

## Voix féminine

1. `make voice-samples` (sur un poste qui joint ElevenLabs) → ouvrir `scenarios/results/voice-samples/index.html`.
   Mêmes 8 phrases (salutation, prix, disponibilité, rupture, correction, confirmation, réclamation, noms) pour chaque
   voix française féminine de votre bibliothèque × `eleven_flash_v2_5` et `eleven_turbo_v2_5`, avec le temps au 1er octet.
   Pas de voix française féminine dans la bibliothèque : elevenlabs.io → Voices → Voice Library → French, Female → Add.
2. Écouter à plusieurs, choisir à l'oreille (chaleur, assurance, débit, aucun ton publicitaire). Puis dans `.env` :
   ```
   VOICE_TTS_VOICE=<id choisi>
   VOICE_TTS_MODEL=eleven_flash_v2_5
   VOICE_TTS_SETTINGS={"stability":0.45,"similarity_boost":0.8,"style":0.15,"speed":1.05}
   ```
   Seul l'agent téléphonique change (chat, commande vocale et marché gardent `TTS_*`). `make restart`.
3. Rejouer H1, H6, H9, H12.

## Retour arrière

- Phrases d'attente : `VOICE_FILLERS=0` (jamais) ou `VOICE_FILLER_AFTER_S=1.2` (plus tard).
- Voix : retirer `VOICE_TTS_*` du `.env`.
- Code : `git revert <commit>` du commit « voice: human, fast, reliable ».
