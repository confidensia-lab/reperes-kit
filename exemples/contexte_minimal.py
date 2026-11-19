"""Le plus petit usage de REPERES dans un agent : récupérer le contexte sourcé d'une question, que
votre modèle exploite pour rédiger, et garder les sources pour les citer.

    export REPERES_API_KEY=rpr_sk_…
    python exemples/contexte_minimal.py "Quels délais pour la révision d'un plan d'aide APA ?"
"""
import sys

from reperes import Reperes

question = " ".join(sys.argv[1:]) or "Quels repères pour construire un projet de service ?"
r = Reperes().context(question)

print(f"Contexte livré ({r.get('delivery')}), opération {r.operation_id}\n")
for i, s in enumerate(r.get("sources") or [], 1):
    print(f"[{i}] {s.get('title')}\n    {s.get('url')}")
# r["context"] contient la doctrine, l'actualité et les preuves à donner au modèle avec la question.
