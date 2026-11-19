"""Agent : boucle entre un modèle et des outils REPERES, avec consignes, garde-fou et trace.

    from reperes.agent import Agent
    from reperes.connexion import ConnexionAPI, outils
    from reperes.modeles import ModeleChat

    c = ConnexionAPI()
    agent = Agent(ModeleChat(), outils(c, ["reperes_context", "reperes_valeur"]), consignes="Tu…")
    r = agent.repondre("Quel est le plafond de l'APA en GIR 1 ?")
    print(r.texte, r.montants_non_sources)

L'agent ne contient aucune règle métier : les consignes disent comment se comporter, les outils
REPERES apportent les règles, les valeurs et les calculs. La conversation se sauve et se recharge
(`etat()`, `Agent(..., messages=…)`), ce qui permet de piloter un agent tour par tour depuis la CLI.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .erreurs import ErreurReperes
from .modeles import Modele
from .outils import Outil

LIMITE_RESULTAT = 60_000  # caractères d'un résultat d'outil rendus au modèle (un résultat de simulation en fait ~25 000)

GARDE_FOU = (
    "\n\nRègle de sourçage : tout montant, taux, seuil ou plafond que tu cites vient d'un résultat d'outil ; "
    "sinon, appelle l'outil adapté ou dis que tu ne l'as pas vérifié. Un article de loi ne se cite que s'il "
    "figure dans un résultat d'outil."
)

# Montants en euros d'un texte : « 1 682,30 € », « 205,10 euros », « 25.50 € ».
# Un montant ne commence jamais collé à une lettre ou un chiffre (« T1 102,28 € » : 102,28, pas 1 102,28).
_MONTANT = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[,.](\d{1,2}))?\s*(?:€|euros?\b)")


def _montants(texte: str) -> set[str]:
    out = set()
    for ent, dec in _MONTANT.findall(texte):
        e = re.sub(r"[\s  ]", "", ent)
        out.add(f"{int(e)}.{(dec or '0').ljust(2, '0')}")
    return out


def _nombres(texte: str) -> set[str]:
    """Nombres d'un résultat d'outil, normalisés au centime (« 205.1 », « 205.10 » → « 205.10 »)."""
    out = set()
    for ent, dec in re.findall(r"(?<![\d.])(\d+)(?:\.(\d+))?", texte):
        out.add(f"{int(ent)}.{(dec or '0')[:2].ljust(2, '0')}")
    return out


SESSION = "reperes.session.v1"

RELANCE = (
    "[Contrôle interne de sourçage, à ne pas mentionner] {montants} ne figure(nt) dans aucun résultat d'outil de "
    "cette conversation. Réécris ta réponse complète pour l'utilisateur, sans évoquer ce contrôle : appuie chaque "
    "montant sur un outil, retire-le, ou indique qu'il est calculé par toi à partir de montants sourcés."
)


@dataclass
class AppelTrace:
    """Un appel d'outil, nommé comme un span OpenTelemetry GenAI `execute_tool`."""

    nom: str
    arguments: dict[str, Any]
    resultat: Any
    erreur: str | None = None
    id: str = ""

    def attributs(self) -> dict[str, Any]:
        """Attributs au vocabulaire OpenTelemetry GenAI (conventions en cours de stabilisation)."""
        a = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": self.nom, "gen_ai.tool.call.id": self.id}
        if self.erreur:
            a["error.type"] = self.erreur
        return a


@dataclass
class Reponse:
    """Réponse rédigée d'un tour, avec les appels d'outils faits pour la produire.

    `montants_non_sources` : montants en euros cités dans le texte qu'aucun résultat d'outil de la
    conversation ne contient ; à vérifier avant diffusion."""

    texte: str
    appels: list[AppelTrace] = field(default_factory=list)
    montants_non_sources: list[str] = field(default_factory=list)
    termine: bool = True

    def vers_json(self) -> dict[str, Any]:
        return {
            "texte": self.texte,
            "termine": self.termine,
            "montants_non_sources": self.montants_non_sources,
            "appels": [{"outil": a.nom, "id": a.id, "arguments": a.arguments, "erreur": a.erreur} for a in self.appels],
        }


class Agent:
    """`modele` : un `Modele` ; `outils` : outils REPERES et outils propres ; `consignes` : le
    comportement attendu ; `garde_fou` : ajoute la règle de sourçage aux consignes ; `trace` : appelé à
    chaque exécution d'outil ; `messages` : conversation à reprendre (`etat()`) ; `limite_resultat` :
    caractères d'un résultat d'outil rendus au modèle."""

    def __init__(self, modele: Modele, outils: list[Outil], consignes: str = "", *, garde_fou: bool = True,
                 relance: bool = True,
                 max_appels: int = 8, trace: Callable[[AppelTrace], None] | None = None,
                 messages: list[dict[str, Any]] | None = None, limite_resultat: int = LIMITE_RESULTAT):
        self.modele = modele
        self.outils = {o.nom: o for o in outils}
        self.max_appels = max_appels
        self.trace = trace
        self.limite_resultat = limite_resultat
        self.relance = relance and garde_fou
        systeme = consignes + (GARDE_FOU if garde_fou else "")
        self.messages: list[dict[str, Any]] = messages or ([{"role": "system", "content": systeme}] if systeme else [])

    def etat(self) -> dict[str, Any]:
        """Conversation à sauver pour la reprendre plus tard (`Agent(..., messages=etat["messages"])`)."""
        return {"schema_version": SESSION, "messages": self.messages}

    def _executer(self, nom: str, arguments: dict[str, Any], ident: str) -> AppelTrace:
        outil = self.outils.get(nom)
        if outil is None:
            return AppelTrace(nom, arguments, None, f"outil inconnu : {nom}", ident)
        try:
            return AppelTrace(nom, arguments, outil.executer(arguments), None, ident)
        except ErreurReperes as e:
            return AppelTrace(nom, arguments, None, str(e), ident)
        except (TypeError, ValueError, KeyError) as e:
            return AppelTrace(nom, arguments, None, f"arguments invalides : {e}", ident)

    def repondre(self, message: str) -> Reponse:
        """Fait répondre le modèle au message, en exécutant ses appels d'outils. Si la réponse cite un
        montant absent des résultats d'outils, le modèle est relancé une fois ; ce qui reste est signalé
        dans `montants_non_sources`, jamais réécrit."""
        self.messages.append({"role": "user", "content": message})
        appels: list[AppelTrace] = []
        relance = self.relance
        for _ in range(self.max_appels):
            tour = self.modele.repondre(self.messages, list(self.outils.values()))
            if not tour.appels:
                self.messages.append({"role": "assistant", "content": tour.texte})
                non_sources = self._non_sources(tour.texte)
                if non_sources and relance:
                    relance = False
                    self.messages.append({"role": "user", "content": RELANCE.format(montants=", ".join(non_sources))})
                    continue
                return Reponse(tour.texte, appels, non_sources)
            self.messages.append({
                "role": "assistant", "content": tour.texte or "",
                "tool_calls": [{"id": a.id, "type": "function", "function": {"name": a.nom, "arguments": json.dumps(a.arguments, ensure_ascii=False)}}
                               for a in tour.appels],
            })
            for a in tour.appels:
                t = self._executer(a.nom, a.arguments, a.id)
                appels.append(t)
                if self.trace:
                    self.trace(t)
                contenu = json.dumps({"erreur": t.erreur} if t.erreur else t.resultat, ensure_ascii=False)
                if len(contenu) > self.limite_resultat:
                    contenu = contenu[: self.limite_resultat] + "…(tronqué)"
                self.messages.append({"role": "tool", "tool_call_id": a.id, "name": a.nom, "content": contenu})
        texte = "Je n'ai pas pu terminer : trop d'appels d'outils pour cette demande."
        self.messages.append({"role": "assistant", "content": texte})
        return Reponse(texte, appels, [], termine=False)

    def _non_sources(self, texte: str) -> list[str]:
        cites = _montants(texte)
        if not cites:
            return []
        connus: set[str] = set()
        for m in self.messages:
            if m.get("role") == "tool":
                connus |= _nombres(str(m.get("content", "")))
            elif m.get("role") == "user" and not str(m.get("content", "")).startswith(RELANCE[:30]):
                # Montants donnés par l'utilisateur ; jamais ceux que cite la relance du contrôle.
                connus |= _montants(str(m.get("content", ""))) | _nombres(str(m.get("content", "")).replace(",", "."))
        return sorted(cites - connus, key=float)
