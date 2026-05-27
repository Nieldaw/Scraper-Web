# Resume du projet

## Vision courte

Le projet consiste a construire un outil interne de veille immobiliere pour centraliser les annonces publiques du canton de Neuchatel, afin de reduire la veille manuelle et aider la prospection.

L'utilisateur final principal est le prospecteur. Il doit pouvoir voir les biens du marche en un seul endroit, suivre les nouveaux biens, les modifications de prix ou d'information, les biens retires, et comparer ces biens avec des mandats de recherche.

## Synthese metier

Le probleme actuel est la dispersion des informations : plusieurs portails, agences, annonces dupliquees ou legerement differentes, donnees incompletes, et beaucoup de temps passe a verifier manuellement. La valeur du projet n'est donc pas de promettre une verite parfaite, mais de donner une vision centralisee, mise a jour et actionnable.

## Perimetre MVP retenu

Le MVP doit rester volontairement strict :

- Canton de Neuchatel uniquement.
- Donnees d'annonces publiques.
- Collecte quotidienne parametree par site.
- Normalisation des annonces.
- Deduplication permissive.
- Historique minimal des changements.
- Exports ou API simples.
- Mandats de recherche.
- Enrichissement SITN uniquement si adresse complete.

## Ce que le MVP ne doit pas faire

Les anciens documents evoquent des idees plus ambitieuses : detection de situations personnelles, scoring d'opportunite sensible, enrichissement de contacts, interface complete, Elasticsearch, WebSocket, etc. Pour la v1, il faut les considerer comme pistes futures ou hors perimetre, sauf validation explicite.

En particulier, la v1 ne doit pas chercher a detecter ou qualifier des situations personnelles comme deces, divorce, problemes financiers ou succession. Elle ne doit pas collecter de telephone/email prive via annuaires. Elle doit aussi eviter tout discours commercial qui transformerait un indice faible en certitude.

## Principe directeur

Le meilleur produit v1 est un outil simple, fiable et controlable : collecter, nettoyer, dedupliquer, historiser, exporter. La validation humaine reste centrale.
