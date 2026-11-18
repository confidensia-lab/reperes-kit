# REPERES — kit de développement

SDK Python et CLI de l'API [REPERES](https://reperes.bmse.fr), l'outil d'expertise du champ social
et médico-social de BMSE : contexte documentaire sourcé, information ponctuelle vérifiée, valeurs de
référence datées et sourcées, simulateurs (rémunération conventionnelle CCN 66 et CCN 51, ESAT,
trajectoire en euros constants, APA à domicile) et réponses rédigées.

Python 3.10 ou plus, aucune dépendance. Licence Apache 2.0.

```bash
pip install reperes
export REPERES_API_KEY=rpr_sk_…
```

La clé se crée sur la [page de connexion MCP](https://reperes.bmse.fr/connecter/mcp) de REPERES,
rubrique « Clés API » ; un compte identifié suffit, l'usage est gratuit dans la franchise mensuelle
([tarifs](https://reperes.bmse.fr/tarifs#api)).

## SDK

```python
from reperes import Reperes, CreditsEpuises

client = Reperes()  # clé lue dans REPERES_API_KEY

smic = client.valeur("smic.horaire", date="2026-03-01")
print(smic["valeurs"][0]["valeur"], smic["valeurs"][0]["source"]["titre"])

plafond = client.valeur("apa.domicile.plafond", coordonnees={"gir": 1})

contexte = client.context("Quels repères pour construire un projet de service ?")
for s in contexte["sources"]:
    print(s["title"], s["url"])

simulation = client.remuneration({
    "convention": "ccn66",
    "emploi": "educateur_specialise",
    "anciennete_ans": 10,
    "type_etablissement": "mecs",
})
print(simulation["statut"], simulation.operation_id)
```

Chaque méthode rend un `Resultat` : le JSON de la réponse, au contrat déclaré dans `schema_version`,
avec `operation_id` (à communiquer au support) et, quand l'opération dépasse la franchise,
`credits_debites` et `credits_restants`.

| Méthode | Route | Contrat |
|---|---|---|
| `context(question, exploration=False)` | `POST /api/v1/context` | contexte sourcé |
| `precision(question)` | `POST /api/v1/precision` | information ponctuelle |
| `answer(question)` | `POST /api/v1/answer` | réponse rédigée |
| `valeur(id, date=, territoire=, coordonnees=)` | `GET /api/v1/valeurs/{id}` | `etalon.result.v1` |
| `historique(id)`, `resoudre(question)`, `rechercher(q, famille=)` | `GET /api/v1/valeurs…` | `etalon.result.v1` |
| `remuneration(profil)`, `modeles()` | `/api/v1/calcul/remuneration`, `/modeles` | `calcul.remuneration.v1` |
| `trajectoire(demande)` | `POST /api/v1/calcul/trajectoire` | `calcul.trajectoire.v1` |
| `esat(demande)` | `POST /api/v1/calcul/esat` | `calcul.esat.v1` |
| `autonomie(scenario)` | `POST /api/v1/calcul/autonomie` | `calcul.autonomie.v1` |
| `source(id, contenu=False)`, `contrats()`, `schema(nom)`, `openapi()` | publics | |

Une simulation non couverte (emploi inconnu, date hors période) rend son résultat avec
`statut: "erreur"` et `statut_http == 422`. Les autres échecs lèvent une erreur typée, sans jamais la
clé ni le texte de la question :

| Erreur | Cas |
|---|---|
| `ErreurConfiguration` | clé absente ou invalide, adresse invalide : rien n'est envoyé |
| `ErreurRequete` | corps ou paramètre refusé (`detail` dit lequel) |
| `ErreurAuthentification` | clé invalide ou révoquée (401) |
| `ErreurDroit` | opération hors du droit du compte (403, `upgrade_url`) |
| `CreditsEpuises` | franchise du mois atteinte, crédits insuffisants (402, `credits_requis`, `solde`) |
| `DebitDepasse` | débit dépassé après les nouvelles tentatives (429, `attente`) |
| `ServiceIndisponible` | API injoignable ou moteur indisponible (non compté) |

Toutes dérivent de `ErreurReperes`. Un débit dépassé est retenté deux fois par défaut, en respectant
`Retry-After` (`Reperes(tentatives=0)` pour s'en passer).

## CLI

```bash
reperes context "Quels repères pour construire un projet de service ?" --exploration
reperes precision "Quelle est la durée maximale d'un CPOM ?"
reperes valeur smic.horaire --date 2026-03-01
reperes valeur apa.domicile.plafond --coord gir=1
reperes valeur "plafond APA GIR 1"
reperes valeur point.ccn66 --historique
reperes remuneration ccn66 educateur_specialise --anciennete 10 --etablissement mecs --oui surclassement_internat
reperes remuneration --modeles
reperes trajectoire ccn66 moniteur_educateur --etablissement ime --lecture carriere --debut 2016
reperes esat --part 35 --effectif 30
reperes autonomie scenario.json --prix 32
reperes contrats
printf '%s' 'Ma question' | reperes context -
```

Le JSON reçu sort sur stdout (`--pretty` pour l'indenter) ; les erreurs sur stderr, avec le code HTTP
et le code d'erreur de l'API. Codes de sortie : 0 succès, y compris un statut métier (`not_found`,
contexte vide) ; 1 erreur HTTP ou réseau, clé absente, ou livraison dégradée (recherche
indisponible, statut d'erreur) ; 2 arguments invalides. Options communes : `--base-url` (sinon
`REPERES_API_URL`), `--timeout` (180 secondes).

## Documentation

- [Démarrage](https://reperes.bmse.fr/docs/demarrage), [référence de l'API](https://reperes.bmse.fr/docs/api)
- [Contrats](https://reperes.bmse.fr/docs/contrats) : le schéma JSON de chaque réponse, champ par champ
- [Connecteur MCP](https://reperes.bmse.fr/docs/mcp) : les mêmes opérations pour un assistant

## Développement

```bash
PYTHONPATH=src:tests python -m unittest discover -s tests -t tests
```
