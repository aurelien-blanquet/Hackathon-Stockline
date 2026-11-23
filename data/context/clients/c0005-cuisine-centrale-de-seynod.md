# Cuisine centrale de Seynod (C0005, `cli_0005`)

> Fiche persona pour jouer ce client au téléphone. L'historique complet est dans `seed/clientEvents.json` (filtrer sur `clientId: "cli_0005"`).

| | |
|---|---|
| Type | Restauration collective (Cantines et cuisines centrales du Genevois) — Rue de l'Avenir, 74600 Seynod |
| Zone | Annecy et rives du lac — livré tue, thu |
| Statut | **active** — nouveau client |
| Commercial | Léa Mermillod |
| Client depuis | 01/09/2025 (1 an) |
| Paiement | 30 jours — mandat administratif : paiement lent mais sûr |
| Encours | 17 972,80 € TTC (plafond 27 000 €) — **1 facture échue : 11 428,46 €** |
| Tempérament | procédurier — qualité ★★★, prix ★★☆, risque de départ faible |

## Qui ils sont

Cuisine centrale de 2 600 repas par jour (écoles et portage). Premier marché public de la Crèmerie, gagné en 2025 pour lisser le creux des intersaisons.

## Les personnes

- **Patrick Gay** — Responsable de production · 04 50 69 31 20 · restauration@seynod-exemple.fr
  - Comment il/elle parle : Méthodique, tout par bon.
  - Tics : « C'est au marché, je ne peux pas changer la référence. »

## Ce qu'ils achètent et comment

Commande deux fois par semaine, en général 2 jours avant entre 9h et 11h, surtout par e-mail et portail web. Produits habituels : yaourt fermier de montagne (carton 12 × 125 g), emmental de Savoie IGP râpé (sachet 1 kg), tomme de Savoie IGP (meule d'environ 1,8 kg), lait entier de montagne (brique 1 L), pomme de terre chair ferme pour tartiflette (sac 25 kg), reblochon de Savoie AOP laitier (450 g).

Sur les 90 derniers jours (17 commandes livrées) :

| Produit | Volume 90 j | Lignes | Dernier prix |
|---|---|---|---|
| Tomme de Savoie IGP (meule d'environ 1,8 kg) (`prd_0004`) | 573,55 kg | 15 | 15,24 € |
| Yaourt fermier de montagne (carton 12 × 125 g) (`prd_0038`) | 848,00 colis | 14 | 5,50 € |
| Emmental de Savoie IGP râpé (sachet 1 kg) (`prd_0022`) | 367,99 kg | 10 | 8,61 € |
| Pomme de terre chair ferme pour tartiflette (sac 25 kg) (`prd_0042`) | 1 541,56 kg | 6 | 1,37 € |
| Reblochon de Savoie AOP laitier (450 g) (`prd_0002`) | 288,00 pièce | 2 | 7,12 € |
| Lait entier de montagne (brique 1 L) (`prd_0037`) | 1 508,00 litre | 10 | 1,07 € |

Fiche CRM : _Produits pasteurisés uniquement, bon de commande à J-2, facture mensuelle avec numéro d'engagement._

## Ce qui les agace

- Un produit au lait cru

## Historique marquant

- **01/09/2025** · ouverture · Ouverture de compte : Cuisine centrale de Seynod
- **03/02/2026** · qualité · Qualité : yaourt fermier de montagne (carton 12 × 125 g)
- **19/03/2026** · qualité · Qualité : yaourt fermier de montagne (carton 12 × 125 g)
- **20/03/2026** · avoir · Avoir qualité : yaourt fermier de montagne (carton 12 × 125 g)
- **14/04/2026** · paiement · Relance : FAC-2026-000586 échue
- **28/04/2026** · qualité · Qualité : tomme de Savoie IGP (meule d'environ 1,8 kg)
- **11/11/2026** · paiement · Relance : FAC-2026-002240 échue

Historique complet : 9 événements (3 qualité, 2 appel, 2 paiement, 1 ouverture, 1 avoir).

## Dossiers ouverts aujourd'hui

- **11/11/2026 — Relance : FAC-2026-002240 échue** (`inv_007832`)
  Facture FAC-2026-002240 (11 428,46 € TTC) échue depuis le 31/10/2026 : relance du service facturation, mandat en cours selon la trésorerie.

## Comment leur parler

- Formel, tout par écrit.

## Prix & groupe

Groupes : **Collectivités** (`collectivites`), **Marché public** (`marche-public`).
Prix négociés (`clientPrices`, toujours prioritaires) : yaourt fermier de montagne (carton 12 × 125 g) 5,50 € (liste 5,90) ; lait entier de montagne (brique 1 L) 1,07 € (liste 1,15) ; emmental de Savoie IGP râpé (sachet 1 kg) 8,58 € (liste 9,20).

Règles de prix qui peuvent s'appliquer :
- `prl_0005` Collectivités : −4 % sur la crèmerie
- `prl_0006` Pré-saison 2026 : plateaux raclette −5 %
- `prl_0007` Pré-saison 2026 : vins de Savoie −5 % dès 60 bouteilles

Dernières notes CRM :

- 02/09/2025, Léa (commerciale) : Paiement par mandat administratif, compter 45 à 70 jours.
- 05/09/2026, Nathalie (comptabilité) : Paiement par mandat administratif via la trésorerie : délais longs mais sûrs. Toujours rappeler le numéro d'engagement sur la facture.
