# REPERES — kit de développement

Framework Python pour construire des agents et des outils sur [REPERES](https://reperes.bmse.fr),
l'outil d'expertise du champ social et médico-social de BMSE : contexte documentaire sourcé,
information ponctuelle vérifiée, valeurs de référence datées et sourcées, simulateurs (rémunération
CCN 66 et CCN 51, ESAT, trajectoire en euros constants, APA à domicile). Les règles, les valeurs et les
calculs viennent de REPERES ; le kit apporte la structure pour s'en servir.

Python 3.10 ou plus, aucune dépendance. Licence Apache 2.0.

```bash
pip install reperes
export REPERES_API_KEY=rpr_sk_…
```

La clé se crée sur la [page de connexion MCP](https://reperes.bmse.fr/connecter/mcp) de REPERES,
rubrique « Clés API » ; un compte identifié suffit, l'usage est gratuit dans la franchise mensuelle
([tarifs](https://reperes.bmse.fr/tarifs#api)).

## Les briques

| Brique | Rôle |
|---|---|
| `reperes.Reperes` | Client de l'API : contexte, précision, réponse rédigée, valeurs, simulateurs, sources, contrats |
| `reperes.connexion` | REPERES par l'API (`ConnexionAPI`) ou par la commande `reperes` (`ConnexionCLI`) : même interface, même résultat |
| `reperes.outils` | Outils pour modèles, tirés du catalogue publié des outils MCP ; formats OpenAI/Mistral et Anthropic ; vos outils propres |
| `reperes.agent` | Boucle modèle ↔ outils, consignes, garde-fou de sourçage des montants, trace, session reprise |
| `reperes.modeles` | Modèles au format de chat OpenAI (Mistral par défaut, OpenAI, serveurs locaux) ; un autre fournisseur s'ajoute en implémentant `Modele` |
| `reperes.kits` | Agents métier prêts à l'emploi : APA à domicile, rémunération conventionnelle, ESAT ; chacun aussi en compétence Agent Skills |

## Un agent en quelques lignes

```python
from reperes.agent import Agent
from reperes.connexion import ConnexionAPI, outils
from reperes.modeles import ModeleChat          # MISTRAL_API_KEY, ou REPERES_MODELE_URL/_CLE/REPERES_MODELE

connexion = ConnexionAPI()                      # ou ConnexionCLI()
agent = Agent(
    ModeleChat(),
    outils(connexion, ["reperes_context", "reperes_valeur", "reperes_autonomie"]),
    consignes="Tu accompagnes les familles d'un service d'aide à domicile. Tu n'attribues jamais de GIR.",
)
r = agent.repondre("Quel reste à charge pour 30 h par mois à 29 €, GIR 2, participation 15 % ?")
print(r.texte)
print(r.montants_non_sources)                  # montants cités sans résultat d'outil : à vérifier
```

- **Outils.** Leurs descriptions et schémas viennent de REPERES (`Reperes.outils_mcp()`), écrits pour
  des modèles : un outil ajouté côté REPERES devient disponible sans modifier le kit. Un outil propre
  se déclare avec `reperes.outils.Outil(nom, description, schema, executer)`.
- **Garde-fou.** Tout montant en euros cité doit figurer dans un résultat d'outil ou dans le message de
  l'utilisateur ; sinon le modèle est relancé une fois, puis le montant est signalé dans
  `montants_non_sources`, jamais réécrit.
- **Trace et session.** `trace=` reçoit chaque appel d'outil (`AppelTrace.attributs()` au vocabulaire
  OpenTelemetry GenAI) ; `agent.etat()` se sauve en JSON (`reperes.session.v1`) et se reprend avec
  `Agent(..., messages=…)`.

## Kits métier

| Kit | Compétence | Outils |
|---|---|---|
| `apa` | `reperes-apa` : maintien à domicile, APA, plan d'aide, reste à charge ; consignes issues des fiches de terrain BMSE | `reperes_autonomie`, `reperes_context`, `reperes_valeur` |
| `remuneration` | `reperes-remuneration` : brut, net, coût employeur CCN 66 et CCN 51, trajectoire | `reperes_calcul`, `reperes_modeles`, `reperes_trajectoire`, `reperes_context`, `reperes_valeur` |
| `esat` | `reperes-esat` : rémunération garantie d'un travailleur d'ESAT | `reperes_calcul`, `reperes_context`, `reperes_valeur` |

```python
from reperes.kits import creer_agent
from reperes.connexion import ConnexionCLI
from reperes.modeles import ModeleChat

agent = creer_agent("apa", ConnexionCLI(), ModeleChat(), consignes_supplementaires="Département : Rhône.")
```

Chaque kit est aussi une compétence au format [Agent Skills](https://agentskills.io) (`SKILL.md` et
`references/consignes.md`, dans `src/reperes/skills/`), source unique de ses consignes. Un agent de
code (Claude Code, Codex…) la charge telle quelle et appelle REPERES par la CLI :

```bash
reperes skills --exporter .claude/skills
```

## CLI

La commande `reperes` sert deux usages : atteindre REPERES depuis un script ou un agent de code, et
piloter un kit.

```bash
# Outils, sans modèle : déterministes, JSON en sortie
reperes outils                                             # catalogue (définitions pour modèles)
reperes outil reperes_autonomie --decrire                  # schéma des arguments
reperes outil reperes_valeur --arguments '{"id": "smic.horaire", "date": "2026-03-01"}'
echo '{"convention": "esat", "part_esat": {"pct_smic": 35}}' | reperes outil reperes_calcul --arguments -

# Opérations
reperes context "Quels repères pour construire un projet de service ?"
reperes valeur apa.domicile.plafond --coord gir=1
reperes remuneration ccn66 educateur_specialise --anciennete 10 --etablissement mecs
reperes esat --part 35 --effectif 30

# Agent d'un kit : conversation, ou un tour par appel avec session et sortie JSON
reperes agent apa
reperes agent remuneration --message "Coût d'un éducateur spécialisé, 10 ans, MECS ?" --session s.json --json
```

Contrat de sortie, stable : le JSON reçu sur stdout, seul ; les erreurs sur stderr
(`--erreurs-json` : objet `{"error", "message", "statut_http", "detail", "upgrade_url"…}`), jamais la
clé ; aucune invite interactive hors `reperes agent` sans `--message`.

| Code | Sens |
|---|---|
| 0 | Succès, y compris un statut métier (`not_found`, contexte vide) |
| 1 | Échec sans résultat : HTTP, réseau, clé, droit, crédits |
| 2 | Arguments invalides |
| 3 | Résultat rendu mais dégradé (simulation `erreur`, valeur indisponible) : le JSON dit pourquoi |

Un agent de code a rarement besoin de `reperes agent` : il est lui-même un modèle. Il charge la
compétence du kit et appelle `reperes outil`. `reperes agent` sert à un humain, à un script ou à un
outil d'automatisation sans modèle.

## Client de l'API

```python
from reperes import Reperes, CreditsEpuises

client = Reperes()
smic = client.valeur("smic.horaire", date="2026-03-01")
simulation = client.remuneration({"convention": "ccn66", "emploi": "educateur_specialise", "anciennete_ans": 10})
print(simulation["statut"], simulation.operation_id, simulation.credits_debites)
```

Chaque méthode rend un `Resultat` : le JSON de la réponse (contrat dans `schema_version`), avec
`operation_id` et, au-delà de la franchise, `credits_debites` et `credits_restants`. Erreurs typées,
sans la clé ni la question : `ErreurConfiguration`, `ErreurRequete`, `ErreurAuthentification`,
`ErreurDroit`, `CreditsEpuises` (`credits_requis`, `solde`), `DebitDepasse` (`attente`),
`ServiceIndisponible`, toutes dérivées de `ErreurReperes`. Un débit dépassé est retenté deux fois en
respectant `Retry-After`.

## Exemples

- [`exemples/agent_personnalise.py`](exemples/agent_personnalise.py) : consignes propres, outils REPERES
  et un outil de votre organisation.
- [`exemples/contexte_minimal.py`](exemples/contexte_minimal.py) : le contexte sourcé d'une question.
- [`exemples/simulation_remuneration.py`](exemples/simulation_remuneration.py) : simulation CCN 66 et
  rejeu avec une hypothèse modifiée.

## Documentation

- [Démarrage](https://reperes.bmse.fr/docs/demarrage), [référence de l'API](https://reperes.bmse.fr/docs/api),
  [contrats](https://reperes.bmse.fr/docs/contrats), [connecteur MCP](https://reperes.bmse.fr/docs/mcp)
- [SDK et framework](https://reperes.bmse.fr/docs/sdk), [CLI](https://reperes.bmse.fr/docs/cli)

## Développement

```bash
PYTHONPATH=src:tests python -m unittest discover -s tests -t tests
```
