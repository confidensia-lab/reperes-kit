# Exemple : agent APA à domicile

Un agent conversationnel qui accompagne une situation de maintien à domicile : besoins, demande
d'APA, plan d'aide, coût réel du plan, factures. Il s'appuie sur REPERES et ne contient lui-même
aucune règle ni valeur :

| Ce que fait l'agent | D'où ça vient |
|---|---|
| Comportement (questions à poser, ce qu'il ne doit jamais affirmer) | `consignes.md`, issues des fiches de terrain BMSE |
| Calcul du plan, de la participation et du reste à charge | `reperes.kits.autonomie` hors ligne, ou l'API (`calcul.autonomie.v1`) |
| Plafonds, MTP, barème, tarifs de référence | Étalon, par l'API ou l'instantané daté |
| Démarches, délais, interlocuteurs, droits | Doctrine et sources de REPERES (`/api/v1/context`) |

Le calcul est un démonstrateur : non opposable, il n'attribue jamais de GIR ni ne déduit de volume
d'heures. Aucune donnée identifiante n'est demandée ni transmise.

## Lancer

```bash
pip install reperes
export REPERES_API_KEY=rpr_sk_…
export MISTRAL_API_KEY=…
python exemples/agent_apa/agent.py
```

Calcul hors ligne sur un instantané daté des valeurs de l'APA :

```bash
python exemples/agent_apa/agent.py --creer-instantane apa.json
python exemples/agent_apa/agent.py --instantane apa.json
```

Autre modèle : `AGENT_URL` (API de chat au format OpenAI), `AGENT_CLE`, `AGENT_MODELE`.

## Adapter

Les consignes se modifient dans `consignes.md`. Pour changer une hypothèse de calcul (tarif horaire,
taux de participation), modifiez le scénario, pas le calculateur : le résultat de référence reste
celui du moteur REPERES, que le kit reproduit au centime.
