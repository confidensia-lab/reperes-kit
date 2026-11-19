"""Kits simulateurs : calculateurs Python des contrats de REPERES, rejouables hors ligne.

Chaque kit implémente un contrat publié (`calcul.autonomie.v1`, `calcul.esat.v1`) sur un instantané
daté des valeurs d'Étalon (`reperes.kits.valeurs.Instantane`) et reproduit au centime le résultat du
moteur REPERES : mêmes lignes, mêmes montants, mêmes statuts, mêmes sources. Les cas de référence du
dépôt (`tests/cas/`) le vérifient à chaque version.

Le kit sert à comprendre un calcul, à le rejouer avec une hypothèse modifiée, à l'intégrer dans un
agent ou un outil sans appel réseau. Le résultat de production reste celui de l'API.
"""
