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

## Installation pour un utilisateur (Windows)

Aucune connaissance technique n'est nécessaire. Il faut un PC Windows 10 ou 11 (64 bits), une connexion
internet pour la première installation, et environ 3 Go d'espace disque.

### 1. Installer Docker Desktop (une seule fois)

> **Automatique :** `demarrer.bat` installe Docker Desktop via `winget` s'il est absent (acceptez la demande
> d'autorisation de Windows, puis redémarrez le PC si on vous le demande et relancez `demarrer.bat`).
> Les étapes manuelles ci-dessous ne servent que si l'installation automatique échoue.

1. Ouvrez <https://www.docker.com/products/docker-desktop/> et cliquez sur **Download for Windows**.
2. Double-cliquez sur le fichier téléchargé (`Docker Desktop Installer.exe`) et laissez les options par défaut
   (gardez cochée l'option **WSL 2**). Acceptez la demande d'autorisation de Windows.
3. Redémarrez le PC si l'installateur le demande.
4. Lancez **Docker Desktop** depuis le menu Démarrer. Acceptez les conditions d'utilisation ; vous pouvez
   ignorer la création de compte (« Skip » ou « Continue without signing in »).
5. Attendez que l'icône de baleine en bas à droite de l'écran cesse de bouger et que Docker indique
   **Engine running** (en bas à gauche de la fenêtre). Cela peut prendre une à deux minutes.

### 2. Récupérer l'application

1. Enregistrez le fichier **`immo-collector.zip`** que l'on vous a envoyé, par exemple sur le Bureau.
2. Clic droit dessus → **Extraire tout…** → choisissez un dossier simple, par exemple `C:\immo-collector`
   (évitez les dossiers synchronisés OneDrive).

### 3. Lancer l'application

1. Vérifiez que **Docker Desktop est lancé** (étape 1.5).
2. Dans le dossier extrait, **double-cliquez sur `demarrer.bat`**.
   - Si Windows affiche « Windows a protégé votre ordinateur » : cliquez sur **Informations complémentaires**,
     puis **Exécuter quand même**. Le fichier est un simple script texte que vous pouvez ouvrir avec le
     Bloc-notes pour vérifier.
3. Une fenêtre noire s'ouvre et affiche l'avancement. **La première fois, comptez 5 à 10 minutes** (téléchargement
   et préparation) ; les fois suivantes, quelques secondes. Ne la fermez pas avant le message
   « L'application est prête ».
4. Votre navigateur s'ouvre tout seul sur **<http://localhost:8000>**. Une visite guidée s'affiche au premier
   lancement.

### 4. Récupérer les premières annonces

L'application démarre **vide**. Allez dans l'onglet **Configuration**, laissez *Anibis* et *NE* cochés, puis cliquez
sur **Lancer la collecte**. Le suivi se fait dans l'onglet **Collectes** ; les biens apparaissent dans **Propriétés**
au bout d'une à deux minutes.

### 5. Arrêter et relancer

- **Arrêter** : double-cliquez sur **`arreter.bat`**. Vos données sont conservées.
- **Relancer** : double-cliquez à nouveau sur `demarrer.bat` (Docker Desktop doit être lancé).
- Fermer simplement le navigateur n'arrête pas l'application ; elle redémarre aussi avec Docker Desktop.
- **Tout effacer** (base de données comprise) : dans le dossier, ouvrez une invite de commandes et tapez
  `docker compose -f docker-compose.app.yml down -v`.

Les fichiers CSV exportés et le cache se trouvent dans le dossier **`data`**, à côté de `demarrer.bat`.

### Problèmes fréquents

| Message ou symptôme | Que faire |
|---|---|
| « Docker Desktop n'est pas lancé » | Ouvrez Docker Desktop, attendez « Engine running », relancez `demarrer.bat` |
| « Docker Desktop n'est pas installé » | `demarrer.bat` l'installe seul ; sinon, étape 1 à la main |
| Docker demande d'activer la virtualisation ou WSL | Redémarrez le PC ; sinon activez la *virtualisation* dans le BIOS (voir l'aide de Docker Desktop) |
| « port is already allocated » / port 8000 déjà utilisé | Un autre programme utilise le port 8000 ; fermez-le puis relancez |
| La page ne s'ouvre pas | Attendez 30 secondes puis actualisez ; sinon tapez `docker compose -f docker-compose.app.yml logs app` |
| *Lookmove a refusé l'accès (HTTP 403)* dans Collectes | Normal : ce site bloque parfois les programmes automatiques. Les autres sources continuent de fonctionner |

Sous macOS ou Linux : même principe avec Docker Desktop (ou Docker Engine), puis `./start.sh` dans le dossier.

*Pour le développeur : `make package` fabrique `dist/immo-collector.zip` (voir `scripts/build_package.py`).*

---

## Tableau de bord (`/`)

- **Compteurs** : total des biens, *Nouveaux*, *Modifiés*, *Plus disponible*. Cliquer sur un compteur ouvre la
  liste des biens correspondants.
- **Dernière collecte** : statut et date de départ ; s'il y a eu une erreur, elle est résumée ici.
- **Derniers nouveaux biens** : jusqu'à 8 cartes des biens les plus récemment vus au statut *Nouveau*.

## Propriétés (`/properties`)

Grille de cartes : photo (ou visuel de remplacement si l'annonce n'a pas d'image exploitable), pastille de
statut, prix, titre, localité, pièces, surface et source.

**Fiabilité du prix** — une petite pastille à côté du prix indique d'où il vient :

- **✓ vérifié** : le prix a été lu sur la fiche de l'annonce ;
- **≈ estimé** : prix de la page de résultats, non confirmé sur la fiche (la source peut l'afficher faux, voir
  « Qualité des données ») ;
- *aucune pastille* : on ne sait pas (autre source, ou donnée collectée avant ce suivi). Ce n'est pas un
  signe que le prix est faux.

L'API expose le même champ : `price_status` (`verified`, `estimated` ou `null`).

**Filtres** (la liste se met à jour toute seule, sans recharger la page) :

- **Recherche** : texte dans le titre, la ville ou l'adresse.
- **Onglets de statut** :
  - *Tous* — tous les biens, y compris les biens « actifs » ni nouveaux ni modifiés ;
  - *Nouveaux* — vus pour la première fois récemment ;
  - *Modifiés* — prix ou contenu changé depuis la dernière collecte ;
  - *Plus disponible* — plus vus depuis 7 jours (réglage `INACTIVE_AFTER_DAYS`) ou retirés.
- **Plus de filtres** (tous en listes déroulantes) : ville (celles présentes en base), canton (`NE`, `VD`…),
  type de bien, prix min/max et pièces min (par paliers), tri (récents, prix croissant ou
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

- **Créer** : nom (obligatoire), puis des critères tous facultatifs :
  - **Villes** : liste déroulante des villes présentes en base, avec recherche et choix multiple.
  - **Type de bien** : cases à cocher Appartement / Maison / Terrain.
  - **Prix, pièces, surface** : curseurs à deux poignées. Une poignée placée à l'extrémité signifie
    « pas de limite » (le critère n'est pas enregistré).
  - **Biens actifs uniquement**.

La collecte ne garde que les **ventes** : une annonce dont l'offre n'est pas « vente » (location, ou offre
indéterminée) est rejetée, de même qu'une annonce dont la fiche indique un prix « par mois ».
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
2. **Cantons** : un ou plusieurs parmi GE, VD, NE, JU, FR, VS. **Les six sont cochés par défaut** ; décochez
   ceux dont vous n'avez pas besoin. Plus il y a de cantons, plus la collecte est longue.
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
  dans ses données brutes (pastille **≈ estimé** sur la carte) et le prix ne doit pas être utilisé tel quel.
- Un prix aberrant peut venir **du vendeur** lui-même (par exemple une maison à 2 141 CHF) : ce n'est pas une
  erreur d'extraction. Le contrôle qualité (`quality_report`) signale les prix trop bas.
- **Surface** : pour un terrain, la surface de la fiche est celle de la parcelle ; elle n'est pas enregistrée comme
  surface habitable.
- **Photos** : récupérées quand l'annonce en fournit une ; sinon un visuel de remplacement s'affiche.

## Importer une page HTML enregistrée

Pour un site que la collecte automatique ne peut pas lire (Homegate, ImmoScout24…) : ouvrez la page de
résultats dans votre navigateur, enregistrez-la (`Ctrl+S`), puis dans **Configuration → Importer une page HTML**
choisissez la source, le canton et le fichier. Seules les annonces de **vente** sont conservées.

## Historique et statut « traité »

- **Historique :** chaque fois qu'une collecte constate un changement de prix, de titre ou d'agence, une ligne est
  ajoutée à la *timeline* en bas de la fiche du bien.
- **Traité :** le bouton « Marquer comme traité » (fiche du bien) retire le bien de la liste lorsque vous cochez
  **Non traités** dans les filtres de la page Propriétés.
- Après une mise à jour du code, lancez `make migrate` pour créer la table d'historique et le champ « traité ».

## Mandats depuis une annonce, coordonnées et infobulles

- **Fiche d'un bien → « Créer un mandat depuis cette annonce »** ouvre le formulaire pré-rempli (ville, type,
  prix ±20 %, pièces ±1, surface ±20 %). Un compteur indique en direct combien de biens correspondent.
- **Coordonnées :** après chaque collecte, le code postal de chaque bien est envoyé (seul) à l'API publique
  geo.admin.ch pour placer la carte. Pour les biens déjà en base : `python -m immo_ne_collector.services.geocoding`.
  Désactivable avec `GEOCODING_ENABLED=false`.
- **Infobulles :** survolez (ou sélectionnez au clavier) les statuts, onglets et filtres pour une explication.
