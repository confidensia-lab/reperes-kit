"""Simulation de rémunération conventionnelle par l'API, puis rejeu avec une hypothèse modifiée.

    export REPERES_API_KEY=rpr_sk_…
    python exemples/simulation_remuneration.py
"""
from reperes import Reperes

client = Reperes()
# Hypothèses employeur de la recette REPERES : effectif 60, AT/MP moyen national 2026, complémentaire
# santé 20 € + 20 €, taxe sur les salaires exclue. Sans elles, le simulateur applique ses repères par
# défaut et le signale.
profil = {
    "convention": "ccn66",
    "emploi": "educateur_specialise",
    "anciennete_ans": 10,
    "type_etablissement": "mecs",
    "employeur": {"effectif": 60, "taux_atmp": "2.08", "mutuelle_employeur": "20", "mutuelle_salarie": "20", "taxe_salaires": False},
}

for anciennete in (10, 20):
    r = client.remuneration({**profil, "anciennete_ans": anciennete})
    print(f"\nÉducateur spécialisé CCN 66, {anciennete} ans d'ancienneté : statut {r['statut']}")
    for bloc in ("brut", "net", "cout"):
        b = r.get(bloc) or {}
        print(f"  {bloc:5} {b.get('total', '—'):>10} €")
    for q in r.get("questions") or []:
        print(f"  question : {q.get('question')}")
    for s in r.get("signalements") or []:
        print(f"  signalement : {s}")
