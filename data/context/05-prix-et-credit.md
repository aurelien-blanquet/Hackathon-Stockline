# Prix et crédit

## Prix de vente

- Tarif de saison d'hiver du 1er décembre au 30 avril, tarif d'été du 1er mai au 30 novembre ; prix de saison bloqués pour les gros comptes contre un engagement de volume.
- Beaufort d'été et fromages fermiers : prix au lot selon l'affinage.
- Franco 150 € HT en station, 100 € à Annecy et dans le Genevois, sinon 15 € de livraison.
- Remises : commerciaux jusqu'à 5 %, au-delà Jean-Marc ; le standard ne peut pas accorder de remise.
- Vins, génépi et bière : TVA 20 %.

Ordre de résolution : prix négocié client > règle de prix (client, puis groupe) > prix liste.

## Groupes de clients

- **Stations** (`stations`) : Restaurants et snacks de station : saison d'hiver de mi-décembre à mi-avril, été en juillet-août.
- **Annecy et lac** (`lac`) : Restaurants ouverts à l'année, pic l'été.
- **Hôtellerie** (`hotellerie`) : Hôtels de station et du lac, demi-pension, factures au mois.
- **Fromageries** (`fromageries`) : Revendeurs exigeants sur l'AOP et l'affinage.
- **Supérettes de station** (`superettes`) : Vente aux vacanciers en location, énorme samedi.
- **Collectivités** (`collectivites`) : Cantines du Genevois, pasteurisé uniquement.
- **Marché public** (`marche-public`) : Prix au bordereau, mandat administratif.
- **Traiteurs et chalets** (`traiteurs`) : Chefs à domicile et conciergeries de chalets.
- **Grands comptes** (`grands-comptes`) : Les plus gros chiffres d'affaires des 12 derniers mois, suivis par la direction.
- **À surveiller** (`a-surveiller`) : Retards de paiement, litiges ou compte bloqué : vérifier l'encours avant toute commande.
- **Clients perdus** (`perdus`) : Plus de commande depuis plusieurs mois (partis à la concurrence ou fermés) : à reconquérir.

## Règles de prix

- `prl_0001` Stations : −5 % sur la raclette en meule dès 30 kg, du 01/12/2025
- `prl_0002` Hôtellerie : −4 % sur les portions et yaourts, du 01/12/2025
- `prl_0003` Fromageries : coût + 22 % sur les fromages de Savoie, du 01/10/2024 — Pour leur laisser la marge de revente.
- `prl_0004` Supérettes : −6 % sur la raclette tranchée dès 50 kg, du 01/12/2025
- `prl_0005` Collectivités : −4 % sur la crèmerie, du 01/09/2025
- `prl_0006` Pré-saison 2026 : plateaux raclette −5 %, du 15/11/2026 au 20/12/2026 — Pré-commandes de début de saison.
- `prl_0007` Pré-saison 2026 : vins de Savoie −5 % dès 60 bouteilles, du 15/11/2026 au 10/12/2026
- `prl_0008` Été 2026 : diots −8 % dès 10 kg (inactive), du 01/07/2026 au 31/08/2026

## Crédit et relances

- Plafond d'encours par client ; au-delà, validation par Nathalie.
- Clients saisonniers : tout doit être soldé avant le 31 mai pour l'hiver et le 30 septembre pour l'été, sinon pas de livraison à l'ouverture suivante.
- Relance à J+7 par mail, J+15 par téléphone, J+30 mise en demeure ; blocage à J+45.
- Collectivités : pas de relance avant J+30 (mandat administratif).

## Clients à surveiller (au 24/11)

- La Grolle des Gets (cli_0007) : mauvais payeur, compte à risque, 12 facture échues pour 93 200,81 € TTC — **bloqué**.
- Snack Le Télésiège (cli_0008) : mauvais payeur, compte à risque, 13 facture échues pour 246 911,01 € TTC — **bloqué**.
- Le Bistrot des Pistes (cli_0021) : paie en retard (3 à 6 semaines), mais finit par payer.
- Le Panier Savoyard du Grand-Bornand (cli_0027) : paie en retard (3 à 6 semaines), mais finit par payer.
- Les Soirées de Sylvie (cli_0036) : paie en retard (3 à 6 semaines), mais finit par payer.
- Restaurant d'altitude Vieille Ville (cli_0040) : paie en retard (3 à 6 semaines), mais finit par payer.
- Restaurant scolaire d'Annecy (cli_0041) : mauvais payeur, compte à risque, 1 facture échue pour 14 001,13 € TTC — **bloqué**.
- Le Bistrot d'Aiguille (cli_0043) : paie en retard (3 à 6 semaines), mais finit par payer, 1 facture échue pour 10 270,27 € TTC.
- Alimentation Legrand (cli_0046) : paie en retard (3 à 6 semaines), mais finit par payer.
- EHPAD Les Camélias (cli_0047) : mandat administratif : paiement lent mais sûr, 1 facture échue pour 18 337,58 € TTC.
- Le Bistrot d'Étale (cli_0050) : paie en retard (3 à 6 semaines), mais finit par payer, 2 facture échues pour 3 424,19 € TTC.
- La Ferme d'Étale (cli_0059) : paie à l'heure mais déduit ce qu'il conteste.
- Supérette d'Annecy-le-Vieux (cli_0062) : paie en retard (3 à 6 semaines), mais finit par payer.
- Hôtel Deschamps (cli_0065) : paie en retard (3 à 6 semaines), mais finit par payer.
- La Ferme de Sofiane (cli_0066) : paie en retard (3 à 6 semaines), mais finit par payer, 3 facture échues pour 5 679,42 € TTC.
