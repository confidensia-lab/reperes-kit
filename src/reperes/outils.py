"""Outils REPERES pour un modèle : catalogue publié, exécution par l'API ou par la CLI, formats des
fournisseurs de modèles.

Un outil est désigné par son nom MCP (`reperes_context`, `reperes_valeur`, `reperes_calcul`…) et reçoit
les arguments décrits par son schéma d'entrée, publié par REPERES et écrit pour des modèles
(`Reperes.outils_mcp()`). Rien n'est recopié ici : un outil ajouté côté REPERES devient disponible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from .erreurs import ErreurConfiguration

if TYPE_CHECKING:
    from .client import Reperes


#: Outils du framework hors du catalogue MCP, avec leur définition pour un modèle.
OUTILS_FRAMEWORK: dict[str, dict[str, Any]] = {
    "reperes_modeles": {
        "name": "reperes_modeles",
        "description": "Catalogue du simulateur de rémunération : emplois (identifiant, libellé, catégorie) d'une "
        "convention, types d'établissement et familles d'éléments variables. À consulter quand l'intitulé d'emploi "
        "donné ne correspond pas exactement à un identifiant.",
        "inputSchema": {"type": "object", "properties": {"convention": {"type": "string", "description": "`ccn66` ou `ccn51` ; toutes si absent."}}},
    },
}


def executer_par_api(client: "Reperes", nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Exécute un outil REPERES par l'API : même correspondance que le connecteur MCP."""
    a = dict(arguments or {})
    if nom in {"reperes_context", "reperes_precision", "reperes_answer"}:
        question = a.get("query")
        if not isinstance(question, str):
            raise ErreurConfiguration("`query` requis.")
        operation = {"reperes_context": client.context, "reperes_precision": client.precision, "reperes_answer": client.answer}[nom]
        return dict(operation(question))
    if nom == "reperes_valeur":
        opts = {"territoire": a.get("territoire"), "coordonnees": a.get("coordonnees")}
        ident = a.get("id")
        if isinstance(ident, str) and ident.strip():
            if a.get("historique") is True:
                return dict(client.historique(ident, **opts))
            return dict(client.valeur(ident, date=a.get("date"), **opts))
        question = a.get("query")
        if not isinstance(question, str):
            raise ErreurConfiguration("`id` ou `query` requis.")
        return dict(client.resoudre(question, date=a.get("date"), **opts))
    if nom == "reperes_calcul":
        if a.get("convention") == "esat":
            a.pop("convention")
            return dict(client.esat(a))
        return dict(client.remuneration(a))
    if nom == "reperes_modeles":
        m = dict(client.modeles())
        convention = a.get("convention")
        if isinstance(convention, str) and convention:
            m["conventions"] = [c for c in m.get("conventions") or [] if isinstance(c, dict) and c.get("convention") == convention]
        return m
    if nom == "reperes_trajectoire":
        return dict(client.trajectoire(a))
    if nom == "reperes_autonomie":
        return dict(client.autonomie(a))
    raise ErreurConfiguration(f"Outil inconnu : {nom}.")


@dataclass
class Outil:
    """Un outil proposé au modèle : nom, description, schéma d'entrée et exécution.

    Les outils REPERES viennent du catalogue publié ; un outil propre à votre agent se déclare de la
    même façon, avec sa fonction `executer(arguments) -> résultat JSON`."""

    nom: str
    description: str
    schema: dict[str, Any]
    executer: Callable[[dict[str, Any]], Any] = field(repr=False)

    def pour_openai(self) -> dict[str, Any]:
        """Format « function » des API de chat compatibles OpenAI (Mistral, OpenAI, serveurs locaux)."""
        return {"type": "function", "function": {"name": self.nom, "description": self.description, "parameters": self.schema}}

    def pour_anthropic(self) -> dict[str, Any]:
        """Format des outils de l'API Messages d'Anthropic."""
        return {"name": self.nom, "description": self.description, "input_schema": self.schema}
