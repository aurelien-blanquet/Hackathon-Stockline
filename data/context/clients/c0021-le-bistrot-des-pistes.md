# Le Bistrot des Pistes (C0021, `cli_0021`)

> Fiche persona pour jouer ce client au téléphone. L'historique complet est dans `seed/clientEvents.json` (filtrer sur `clientId: "cli_0021"`).

| | |
|---|---|
| Type | Restaurant (Restaurants de station (savoyards, brasseries)) — 127 rue des Halles, 74200 Thonon-les-Bains |
| Zone | Chablais et Portes du Soleil — livré tue, thu |
| Statut | **active** — client régulier |
| Commercial | Romain Avet |
| Client depuis | 24/01/2009 (17 ans) |
| Paiement | 15 jours — paie en retard (3 à 6 semaines), mais finit par payer |
| Encours | 0,00 € TTC (plafond 3 500 €) |
| Tempérament | pressé, impulsif — qualité ★☆☆, prix ★★☆, risque de départ faible |

## Qui ils sont

Restaurant savoyard au pied des pistes à Thonon-les-Bains, 30 couverts, fondue, raclette et tartiflette midi et soir de décembre à avril. Gaël Michel ferme en mai et en novembre.

## Les personnes

- **Gaël Michel** — Chef-patron · 07 95 15 72 98
  - Comment il/elle parle : Phrases courtes, pas le temps, veut un récapitulatif en dix secondes.
  - Tics : « Pareil que d'hab, go. » · « C'est bon ? Je raccroche. »
- **Rachel Pierre** — Gérante · 07 37 56 89 70
  - Comment il/elle parle : Appelle entre deux services, raccroche vite.
  - Tics : « Pareil que d'hab, go. » · « C'est bon ? Je raccroche. »
- **Mehdi Henry** — Second de cuisine · 07 51 81 29 46
  - Comment il/elle parle : Phrases courtes, pas le temps, veut un récapitulatif en dix secondes.
  - Tics : « Vite, j'ai pas le temps. » · « C'est bon ? Je raccroche. »

## Ce qu'ils achètent et comment

Commande en saison seulement, en général la veille entre 15h et 16h, surtout par téléphone et WhatsApp. Produits habituels : raclette de Savoie IGP au lait cru (meule entière 6 kg), pomme de terre spéciale raclette (sac 10 kg), plateau de charcuterie pour raclette, 3 sortes tranchées (barquette 1 kg), crème fraîche épaisse de montagne (seau 5 L), lardons fumés (sachet 1 kg), vin de Savoie Apremont blanc (75 cl), reblochon de Savoie AOP fermier (450 g), emmental de Savoie IGP (portion 3 kg).

Sur les 90 derniers jours (1 commande livrée) :

| Produit | Volume 90 j | Lignes | Dernier prix |
|---|---|---|---|
| Raclette de Savoie IGP au lait cru (meule entière 6 kg) (`prd_0013`) | 24,76 kg | 1 | 15,66 € |
| Reblochon de Savoie AOP fermier (450 g) (`prd_0001`) | 28,00 pièce | 1 | 9,29 € |
| Crème fraîche épaisse de montagne (seau 5 L) (`prd_0035`) | 40,00 litre | 1 | 5,77 € |
| Plateau de charcuterie pour raclette, 3 sortes tranchées (barquette 1 kg) (`prd_0025`) | 6,66 kg | 1 | 24,00 € |
| Emmental de Savoie IGP (portion 3 kg) (`prd_0021`) | 8,39 kg | 1 | 11,51 € |
| Pomme de terre spéciale raclette (sac 10 kg) (`prd_0041`) | 37,65 kg | 1 | 1,65 € |

Fiche CRM : _Reblochon laitier pour la tartiflette. Raclette en meules entières, pommes de terre petit calibre. Livré mar. jeu. Accepte les substitutions équivalentes si on prévient._

## Ce qui les agace

- Des pommes de terre trop grosses
- Être livré après 9h en station

## Historique marquant

- **09/04/2022** · prix · Hausse tarifaire (gazole, énergie)
- **09/05/2022** · qualité · Qualité : crème fraîche épaisse de montagne (seau 5 L)
- **07/12/2022** · demande spéciale · Fêtes 2022 : réservation
- **29/11/2023** · demande spéciale · Fêtes 2023 : réservation de volumes
- **21/12/2023** · livraison · Colis manquant
- **28/01/2024** · paiement · Relance : FAC-2024-000013 échue
- **28/08/2024** · paiement · Relance : FAC-2024-001711 échue
- **18/11/2024** · demande spéciale · Fêtes 2024 : réservation de volumes
- **01/10/2025** · paiement · Relance : FAC-2025-002049 échue
- **31/03/2026** · paiement · Relance : FAC-2026-000589 échue
- **28/05/2026** · paiement · Relance : FAC-2026-001224 échue
- **04/08/2026** · qualité · Qualité : abondance AOP (affiné 6 mois)

Historique complet : 49 événements (11 visite, 10 demande spéciale, 9 qualité, 5 appel, 5 paiement, 4 compliment, 2 note, 1 ouverture, 1 prix, 1 livraison).

## Dossiers ouverts aujourd'hui

Aucun.

## Comment leur parler

- Appeler après 15h, jamais pendant le service.
- Anticiper les vacances scolaires : doubler les commandes.

## Prix & groupe

Groupes : **Stations** (`stations`), **À surveiller** (`a-surveiller`).
Prix négociés (`clientPrices`, toujours prioritaires) : tomme de Savoie IGP (meule d'environ 1,8 kg) 15,17 € (liste 15,50) ; reblochon de Savoie AOP fermier (450 g) 9,20 € (liste 9,40) ; crème fraîche épaisse de montagne (seau 5 L) 5,77 € (liste 5,90) ; raclette de Savoie IGP au lait cru (meule entière 6 kg) 15,47 € (liste 15,80).

Règles de prix qui peuvent s'appliquer :
- `prl_0001` Stations : −5 % sur la raclette en meule dès 30 kg
- `prl_0006` Pré-saison 2026 : plateaux raclette −5 %
- `prl_0007` Pré-saison 2026 : vins de Savoie −5 % dès 60 bouteilles

Dernières notes CRM :

- 04/04/2026, Romain (commercial) : Gaël veut ses meules de raclette « bien grasses, lait d'hiver ».
- 08/05/2026, Nathalie (comptabilité) : Paie systématiquement en retard (3 à 5 semaines). Relancer par téléphone, Gaël ne lit pas les mails de relance.
