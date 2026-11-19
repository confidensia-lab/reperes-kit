---
name: reperes-apa
description: "Accompagner une situation de maintien à domicile d'une personne âgée en France : demande d'APA, évaluation, plan d'aide, coût réel et reste à charge, factures et heures, avec les règles, valeurs et calculs officiels de REPERES. À utiliser quand il est question d'APA à domicile, de GIR, de plan d'aide, de participation, de reste à charge d'un service d'aide à domicile ou d'aide aux proches aidants."
license: Apache-2.0
---

# APA à domicile avec REPERES

REPERES apporte les règles, les valeurs officielles datées et les calculs ; cette compétence dit
comment les utiliser et comment se comporter. Les consignes complètes sont dans
[references/consignes.md](references/consignes.md).

## Prérequis

```bash
pip install reperes
export REPERES_API_KEY=rpr_sk_…   # clé créée sur https://reperes.bmse.fr/connecter/mcp
```

## Appeler REPERES

Chaque outil s'appelle par la commande `reperes outil`, arguments JSON sur l'entrée standard, résultat
JSON sur la sortie standard. Le schéma des arguments d'un outil : `reperes outil <nom> --decrire`.

```bash
reperes outil reperes_autonomie --arguments - <<'JSON'
{"periode": "2026-01",
 "personne": {"gir": 2, "provenance": "notification"},
 "plan": {"aide_humaine": {"heures": 30, "tarif": 25.5}, "taux_participation": 15, "provenance": "notification"},
 "realise": {"heures_dans_plan": 28, "prix_horaire": 29, "provenance": "facture"}}
JSON
reperes outil reperes_valeur --arguments '{"id": "apa.domicile.plafond", "coordonnees": {"gir": 2}}'
reperes outil reperes_context --arguments '{"query": "Délai de traitement d'une demande d'APA"}'
```

Codes de sortie : 0 résultat ; 3 résultat rendu mais dégradé (statut `erreur`, valeur indisponible :
le JSON dit pourquoi) ; 1 échec sans résultat (clé, droit, crédits, réseau : erreur JSON sur la sortie
d'erreur avec `--erreurs-json`) ; 2 arguments invalides.

## Règles

- Lire [references/consignes.md](references/consignes.md) avant de répondre et s'y tenir.
- Ne jamais calculer à la main un montant qu'un outil produit ; citer les montants, taux et articles
  tels que les résultats d'outils les donnent, avec leurs sources.
- Ne transmettre aucune donnée identifiante (nom, adresse, numéro de dossier).
