"""Un agent à vous, construit sur REPERES : vos consignes, une sélection d'outils REPERES et un outil
propre à votre organisation.

    export REPERES_API_KEY=rpr_sk_…
    export MISTRAL_API_KEY=…
    python exemples/agent_personnalise.py "Quel reste à charge pour 30 h à 29 €/h en GIR 2 ?"
"""
import sys

from reperes.agent import Agent
from reperes.connexion import ConnexionAPI, outils
from reperes.modeles import ModeleChat
from reperes.outils import Outil

# Un outil propre : ici, les tarifs pratiqués par votre service (à remplacer par votre système).
TARIFS = {"aide_humaine_semaine": "29.00", "aide_humaine_dimanche": "36.25"}
tarifs_du_service = Outil(
    nom="tarifs_du_service",
    description="Tarifs horaires facturés par notre service d'aide à domicile, en euros.",
    schema={"type": "object", "properties": {}},
    executer=lambda arguments: TARIFS,
)

consignes = (
    "Tu es l'assistant d'accueil d'un service d'aide à domicile. Tu expliques aux familles le coût réel "
    "d'une intervention avec l'APA. Tu utilises nos tarifs (tarifs_du_service) et le calcul REPERES "
    "(reperes_autonomie) ; tu n'attribues jamais de GIR."
)

connexion = ConnexionAPI()
agent = Agent(
    ModeleChat(),
    [*outils(connexion, ["reperes_autonomie", "reperes_valeur"]), tarifs_du_service],
    consignes,
    trace=lambda t: print(f"  · {t.nom}", file=sys.stderr),
)
reponse = agent.repondre(" ".join(sys.argv[1:]) or "Quel reste à charge pour 30 h par mois en GIR 2, participation 15 % ?")
print(reponse.texte)
if reponse.montants_non_sources:
    print(f"\n[À vérifier : {', '.join(reponse.montants_non_sources)}]", file=sys.stderr)
