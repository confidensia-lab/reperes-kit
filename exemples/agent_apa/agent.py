"""Exemple d'agent APA à domicile, construit sur REPERES.

L'agent converse avec l'utilisateur, extrait les faits utiles au calcul, appelle le calculateur APA
(hors ligne sur un instantané daté, ou par l'API), cherche la doctrine et les valeurs officielles dans
REPERES, et pose la question suivante qui débloque le calcul. Ses consignes (`consignes.md`) viennent
des fiches de terrain BMSE ; aucune règle ni valeur n'est écrite dans ce fichier : elles viennent des
contrats et d'Étalon.

    export REPERES_API_KEY=rpr_sk_…
    export MISTRAL_API_KEY=…                 # ou AGENT_URL / AGENT_CLE pour un autre service
    python exemples/agent_apa/agent.py
    python exemples/agent_apa/agent.py --instantane apa.json   # calcul hors ligne

Le modèle est appelé par l'API de chat au format OpenAI (Mistral, OpenAI, serveur local compatible) :
`AGENT_URL` (défaut https://api.mistral.ai/v1), `AGENT_CLE` (défaut MISTRAL_API_KEY), `AGENT_MODELE`
(défaut mistral-large-latest). `AGENT_TRACE=1` affiche les arguments et les résultats des outils.
Bibliothèque standard seule.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from reperes import ErreurReperes, Reperes
from reperes.kits import autonomie
from reperes.kits.valeurs import Instantane

CONSIGNES = (Path(__file__).parent / "consignes.md").read_text(encoding="utf-8")
LIMITE_OUTIL = 12_000  # caractères rendus au modèle par appel d'outil

OUTILS_REPERES = [
    {
        "type": "function",
        "function": {
            "name": "contexte_reperes",
            "description": "Doctrine, textes et sources de REPERES sur une question (démarche, délai, droit, interlocuteur).",
            "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "valeur_reperes",
            "description": "Valeur officielle datée et sourcée (plafond APA d'un GIR, MTP, tarif de référence…) : identifiant ou question en français.",
            "parameters": {
                "type": "object",
                "properties": {"cible": {"type": "string"}, "date": {"type": "string", "description": "AAAA-MM-JJ"}},
                "required": ["cible"],
            },
        },
    },
]


def outils_du_modele(reperes: Reperes) -> list[dict]:
    """Outils proposés au modèle. Le calcul reprend la description et le schéma d'entrée de l'outil
    MCP `reperes_autonomie`, publiés par REPERES et écrits pour des modèles : rien n'est recopié ici."""
    mcp = {o["name"]: o for o in reperes.outils_mcp()}
    apa = mcp["reperes_autonomie"]
    calcul = {"type": "function", "function": {"name": "calculer_apa", "description": apa["description"], "parameters": apa["inputSchema"]}}
    return [calcul, *OUTILS_REPERES]


def borne(v: Any) -> str:
    t = json.dumps(v, ensure_ascii=False)
    return t if len(t) <= LIMITE_OUTIL else t[:LIMITE_OUTIL] + "…(tronqué)"


class Outils:
    """Exécution des outils : calcul hors ligne si un instantané est donné, sinon par l'API."""

    def __init__(self, reperes: Reperes, instantane: Instantane | None):
        self.reperes = reperes
        self.instantane = instantane

    def calculer_apa(self, **scenario: Any) -> Any:
        if self.instantane is not None:
            return autonomie.calculer(scenario, self.instantane)
        return dict(self.reperes.autonomie(scenario))

    def contexte_reperes(self, question: str) -> Any:
        r = self.reperes.context(question)
        return {"context": r.get("context"), "sources": [
            {k: s.get(k) for k in ("title", "url", "snippet")} for s in r.get("sources") or []
        ]}

    def valeur_reperes(self, cible: str, date: str | None = None) -> Any:
        if "." in cible and " " not in cible:
            return dict(self.reperes.valeur(cible, date=date))
        return dict(self.reperes.resoudre(cible, date=date))

    def executer(self, nom: str, arguments: dict) -> str:
        f: Callable[..., Any] | None = getattr(self, nom, None) if nom in {"calculer_apa", "contexte_reperes", "valeur_reperes"} else None
        if f is None:
            return borne({"erreur": f"outil inconnu : {nom}"})
        try:
            return borne(f(**arguments))
        except ErreurReperes as e:
            return borne({"erreur": str(e)})
        except (TypeError, ValueError, KeyError) as e:
            return borne({"erreur": f"arguments invalides : {e}"})


def texte(contenu: Any) -> str:
    """Texte d'une réponse : chaîne, ou liste de blocs dont seuls les blocs `text` sont rendus
    (certains modèles y joignent des blocs de raisonnement)."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "".join(b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text")
    return ""


def discuter(url: str, cle: str, modele: str, messages: list[dict], outils: list[dict]) -> dict:
    """Un tour de l'API de chat au format OpenAI, avec outils."""
    corps = json.dumps({"model": modele, "messages": messages, "tools": outils, "tool_choice": "auto", "temperature": 0.2}).encode()
    req = Request(f"{url.rstrip('/')}/chat/completions", data=corps, method="POST",
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {cle}"})
    with urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]


def tour(outils: Outils, definitions: list[dict], url: str, cle: str, modele: str, messages: list[dict], max_appels: int = 8) -> str:
    """Fait répondre le modèle, en exécutant ses appels d'outils, jusqu'à une réponse rédigée."""
    for _ in range(max_appels):
        m = discuter(url, cle, modele, messages, definitions)
        appels = m.get("tool_calls") or []
        messages.append({k: v for k, v in m.items() if k in {"role", "content", "tool_calls"}})
        if not appels:
            return texte(m.get("content"))
        for a in appels:
            nom = a["function"]["name"]
            try:
                args = json.loads(a["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            resultat = outils.executer(nom, args)
            print(f"  · {nom}", file=sys.stderr)
            if os.getenv("AGENT_TRACE"):
                print(f"    arguments : {json.dumps(args, ensure_ascii=False)[:600]}\n    résultat : {resultat[:600]}", file=sys.stderr)
            messages.append({"role": "tool", "tool_call_id": a.get("id"), "name": nom, "content": resultat})
    return "Je n'ai pas pu terminer : trop d'appels d'outils pour cette question."


def main() -> int:
    p = argparse.ArgumentParser(description="Agent APA à domicile construit sur REPERES.")
    p.add_argument("--instantane", help="instantané Étalon (JSON) pour calculer hors ligne")
    p.add_argument("--creer-instantane", metavar="FICHIER", help="lit les valeurs de l'APA sur l'API et les fige dans FICHIER, puis s'arrête")
    a = p.parse_args()

    reperes = Reperes()
    if a.creer_instantane:
        Instantane.depuis_api(reperes, autonomie.PARAMETRES).sauver(a.creer_instantane)
        print(f"Instantané écrit : {a.creer_instantane}")
        return 0
    url = os.getenv("AGENT_URL", "https://api.mistral.ai/v1")
    cle = os.getenv("AGENT_CLE") or os.getenv("MISTRAL_API_KEY", "")
    modele = os.getenv("AGENT_MODELE", "mistral-large-latest")
    if not cle:
        print("Clé du modèle absente : AGENT_CLE ou MISTRAL_API_KEY.", file=sys.stderr)
        return 1
    outils = Outils(reperes, Instantane.charger(a.instantane) if a.instantane else None)
    definitions = outils_du_modele(reperes)
    messages: list[dict] = [{"role": "system", "content": CONSIGNES}]
    print("Agent APA à domicile (REPERES). Décrivez la situation ; ligne vide pour quitter.\n")
    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            break
        if not q:
            break
        messages.append({"role": "user", "content": q})
        print("\n" + tour(outils, definitions, url, cle, modele, messages) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
