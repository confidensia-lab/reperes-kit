---
name: reperes-remuneration
description: "Estimer une rémunération conventionnelle du secteur social et médico-social (CCN 66, CCN 51) : brut, net, coût employeur, questions d'attribution des indemnités, évolution en euros courants et constants, avec le simulateur et les textes de REPERES. À utiliser pour une question de salaire, de grille, d'ancienneté, d'indemnité ou de coût d'un poste dans ces conventions."
license: Apache-2.0
---

# Rémunération conventionnelle avec REPERES

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
reperes outil reperes_modeles --arguments '{"convention": "ccn66"}'
reperes outil reperes_calcul --arguments '{"convention": "ccn66", "emploi": "educateur_specialise", "anciennete_ans": 10, "type_etablissement": "mecs"}'
reperes outil reperes_trajectoire --arguments '{"profil": {"convention": "ccn66", "emploi": "moniteur_educateur", "type_etablissement": "ime"}, "lecture": "carriere", "debut": 2016}'
```

Codes de sortie : 0 résultat ; 3 résultat rendu mais dégradé (statut `erreur`, valeur indisponible :
le JSON dit pourquoi) ; 1 échec sans résultat (clé, droit, crédits, réseau : erreur JSON sur la sortie
d'erreur avec `--erreurs-json`) ; 2 arguments invalides.

## Règles

- Lire [references/consignes.md](references/consignes.md) avant de répondre et s'y tenir.
- Ne jamais calculer à la main un montant qu'un outil produit ; citer les montants, taux et articles
  tels que les résultats d'outils les donnent, avec leurs sources.
- Ne transmettre aucune donnée identifiante (nom, adresse, numéro de dossier).
