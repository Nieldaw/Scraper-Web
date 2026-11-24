# Guide d'utilisation de l'interface

Interface web du collecteur d'annonces immobilières (vente, Romandie : GE, VD, NE, JU, FR, VS).
Lancement : `make run` puis ouvrir <http://localhost:8000>.

La barre latérale donne accès à toutes les pages. La barre du haut contient une recherche rapide :
elle ouvre la page *Propriétés* filtrée sur le texte saisi.

| Onglet | Rôle en une ligne |
|---|---|
| Tableau de bord | Vue d'ensemble : compteurs, dernière collecte, derniers nouveaux biens |
| Propriétés | Parcourir, filtrer et consulter les biens collectés |
| Mandats | Enregistrer des critères de recherche et voir les biens qui y correspondent |
| Collectes | Historique des collectes et diagnostic des avertissements/erreurs |
| Configuration | Choisir sources et cantons, lancer une collecte |
| Analysis, Chat, User & Account | Pas encore disponibles (« Bientôt disponible ») |

---

## Tableau de bord (`/`)

- **Compteurs** : total des biens, *Nouveaux*, *Modifiés*, *Inactifs*. Cliquer sur un compteur ouvre la
  liste des biens correspondants.
- **Dernière collecte** : statut et date de départ ; s'il y a eu une erreur, elle est résumée ici.
- **Derniers nouveaux biens** : jusqu'à 8 cartes des biens les plus récemment vus au statut *Nouveau*.

## Propriétés (`/properties`)

Grille de cartes : photo (ou visuel de remplacement si l'annonce n'a pas d'image exploitable), pastille de
statut, prix, titre, localité, pièces, surface et source.

**Filtres** (la liste se met à jour toute seule, sans recharger la page) :

- **Recherche** : texte dans le titre, la ville ou l'adresse.
- **Onglets de statut** :
  - *Tous* — tous les biens, y compris les biens « actifs » ni nouveaux ni modifiés ;
  - *Nouveaux* — vus pour la première fois récemment ;
  - *Modifiés* — prix ou contenu changé depuis la dernière collecte ;
  - *Inactifs* — plus vus depuis 7 jours (réglage `INACTIVE_AFTER_DAYS`) ou retirés.
- **Plus de filtres** : ville, canton (`NE`, `VD`…), prix min/max, pièces min, tri (récents, prix croissant ou
  décroissant).

L'adresse de la page garde les filtres : vous pouvez la mettre en favori ou la partager. La pagination
affiche 24 biens par page.

**Fiche d'un bien** (clic sur une carte) : prix, pièces, surface, type, dates de première et dernière
observation, statut SITN, et le tableau des **annonces sources** (un même bien peut venir de plusieurs
sites ; les doublons probables sont fusionnés, mais la déduplication reste volontairement prudente : en cas de
doute, deux annonces restent séparées). Chaque ligne a un lien vers l'annonce d'origine.

Le bouton **Nouveau mandat** ouvre la page *Mandats*.

## Mandats (`/mandates`)

Un mandat est une recherche enregistrée pour un prospecteur.

- **Créer** : nom (obligatoire), villes (séparées par des virgules), types de bien, prix min/max, pièces
  min/max, surface min/max, et « Biens actifs uniquement ». Tous les critères sont facultatifs sauf le nom.
- **Consulter** : cliquer sur un mandat affiche le nombre de biens qui correspondent et leurs cartes (les
  100 premiers).
- Aucun envoi de notification n'est fait pour l'instant : un mandat est une vue, à consulter à la demande.

## Collectes (`/runs`)

Historique des 50 dernières collectes, la plus récente en haut. Pour chacune :

- un **statut** : *Réussie*, *Avertissements* (la collecte a abouti mais une source a rencontré un problème),
  *Partielle* (au moins une source en échec), *Échec* (la collecte s'est arrêtée) ou *En cours…* ;
- les chiffres : biens collectés, nouveaux, mis à jour, durée ;
- le nombre d'**erreurs** et d'**avertissements**.

En dépliant une collecte, on voit **chaque source et chaque canton** avec ses compteurs et, le cas échéant, la
cause en clair et la marche à suivre. Exemples :

| Message | Signification | Que faire |
|---|---|---|
| *Lookmove a refusé l'accès (HTTP 403)* | Le site bloque les requêtes automatisées | Réessayer plus tard. Le projet **ne contourne pas** les protections anti-bot |
| *Limite le débit (HTTP 429)* | Trop de requêtes | Réduire le nombre de pages, réessayer plus tard |
| *N'a pas répondu à temps* | Délai dépassé | Réessayer |
| *Fiches de détail Anibis : prix non vérifiés* | Les fiches n'ont pas toutes été lues (plafond, blocage, ou option désactivée) | Voir « Qualité des données » ci-dessous |

La section « Détails techniques » reprend les messages bruts. Si la collecte a planté, le message d'erreur et la
fin du journal sont affichés ; le journal complet est dans `data/logs/`.

Pendant une collecte, la page se rafraîchit toute seule toutes les 4 secondes.

## Configuration (`/settings`)

Permet de lancer une collecte sans terminal.

1. **Sources** : Anibis, Lookmove. Homegate et ImmoScout24 sont affichés mais grisés : ils sont désactivés
   (protection anti-bot ; leur HTML en cache peut seulement être analysé en ligne de commande).
2. **Cantons** : un ou plusieurs parmi GE, VD, NE, JU, FR, VS.
3. **Limites** (volontairement basses, par respect des sites) : pages par source et canton (1 à 5), nombre
   maximum d'annonces par source, et pour Anibis le nombre maximum de fiches de détail ouvertes.
4. **Lancer la collecte** : la collecte démarre en arrière-plan et vous êtes redirigé vers *Collectes*.

Une seule collecte peut tourner à la fois ; si l'une est déjà en cours, le bouton est désactivé.

Équivalent en ligne de commande :

```bash
make collect-once                                  # toute la Romandie, 3 pages
python -m immo_ne_collector.jobs.daily_collect --canton NE,VD --sources anibis --max-pages 1 \
    --max-listings 10 --max-details 10 --no-export
```

## Analysis, Chat, User & Account

Pages réservées pour plus tard : elles affichent « Bientôt disponible ». Il n'y a pas d'authentification
dans cette version.

---

## Qualité des données — à lire

- **Anibis** : les prix, titres et nombres de pièces de la *page de résultats* ne sont pas fiables (ils diffèrent
  de ceux de la fiche de l'annonce, et varient d'un chargement à l'autre). Par défaut, le collecteur ouvre donc
  la **fiche de chaque annonce** conservée (délai d'1 s entre deux requêtes, plafond configurable, cache
  réutilisé 24 h) pour lire le prix, les pièces, la surface habitable et l'adresse exacts. Sans cela
  (`--no-enrich-details`, plafond dépassé ou blocage), le bien est marqué `price_status = unverified_search_page`
  dans ses données brutes et le prix ne doit pas être utilisé tel quel.
- Un prix aberrant peut venir **du vendeur** lui-même (par exemple une maison à 2 141 CHF) : ce n'est pas une
  erreur d'extraction. Le contrôle qualité (`quality_report`) signale les prix trop bas.
- **Surface** : pour un terrain, la surface de la fiche est celle de la parcelle ; elle n'est pas enregistrée comme
  surface habitable.
- **Photos** : récupérées quand l'annonce en fournit une ; sinon un visuel de remplacement s'affiche.
