---
name: reperes-esat
description: "Comprendre la rémunération garantie d'un travailleur d'ESAT en France : part de l'ESAT, aide au poste, bornes, cotisations, net du travailleur et coût pour l'ESAT, avec le calcul et les textes de REPERES. À utiliser pour une question de rémunération, d'aide au poste ou de coût d'un travailleur d'ESAT."
license: Apache-2.0
---

# Rémunération garantie en ESAT avec REPERES

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
reperes outil reperes_calcul --arguments '{"convention": "esat", "part_esat": {"pct_smic": 35}, "effectif": 30}'
reperes outil reperes_context --arguments '{"query": "Aide au poste en ESAT : règles de calcul"}'
```

Codes de sortie : 0 résultat ; 3 résultat rendu mais dégradé (statut `erreur`, valeur indisponible :
le JSON dit pourquoi) ; 1 échec sans résultat (clé, droit, crédits, réseau : erreur JSON sur la sortie
d'erreur avec `--erreurs-json`) ; 2 arguments invalides.

## Règles

- Lire [references/consignes.md](references/consignes.md) avant de répondre et s'y tenir.
- Ne jamais calculer à la main un montant qu'un outil produit ; citer les montants, taux et articles
  tels que les résultats d'outils les donnent, avec leurs sources.
- Ne transmettre aucune donnée identifiante (nom, adresse, numéro de dossier).
