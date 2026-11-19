"""Kits métier : des agents prêts à l'emploi, assemblés à partir du framework.

Un kit réunit des consignes (le comportement attendu, sans règle ni valeur), une sélection d'outils
REPERES et une description. Les règles, les valeurs et les calculs viennent de REPERES, par l'API ou
par la CLI.

    from reperes.kits import KITS, creer_agent
    from reperes.connexion import ConnexionCLI
    from reperes.modeles import ModeleChat

    agent = creer_agent("apa", ConnexionCLI(), ModeleChat())
    print(agent.repondre("Ma mère, GIR 2, a un plan de 30 heures…").texte)

En ligne de commande : `reperes agent apa`.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Callable

from ..agent import Agent, AppelTrace
from ..connexion import Connexion, outils
from ..modeles import Modele
from ..outils import Outil


@dataclass(frozen=True)
class Kit:
    nom: str
    titre: str
    description: str
    outils: tuple[str, ...]
    fichier_consignes: str

    @property
    def consignes(self) -> str:
        return files(__package__).joinpath("consignes", self.fichier_consignes).read_text(encoding="utf-8")


KITS: dict[str, Kit] = {
    k.nom: k
    for k in (
        Kit("apa", "APA à domicile",
            "Situation de maintien à domicile, demande d'APA, plan d'aide, reste à charge, factures. Consignes issues des fiches de terrain BMSE.",
            ("reperes_autonomie", "reperes_context", "reperes_valeur"), "apa.md"),
        Kit("remuneration", "Rémunération conventionnelle",
            "Brut, net et coût employeur d'un emploi CCN 66 ou CCN 51, questions du simulateur, évolution en euros constants.",
            ("reperes_calcul", "reperes_modeles", "reperes_trajectoire", "reperes_context", "reperes_valeur"), "remuneration.md"),
        Kit("esat", "Rémunération garantie en ESAT",
            "Part de l'ESAT, aide au poste, cotisations, net du travailleur et coût pour l'ESAT.",
            ("reperes_calcul", "reperes_context", "reperes_valeur"), "esat.md"),
    )
}


def creer_agent(kit: str | Kit, connexion: Connexion, modele: Modele, *, outils_propres: list[Outil] | None = None,
                consignes_supplementaires: str = "", trace: Callable[[AppelTrace], None] | None = None,
                messages: list[dict[str, Any]] | None = None, **options: Any) -> Agent:
    """Agent d'un kit : ses consignes (complétées au besoin), ses outils REPERES et vos outils propres."""
    k = KITS[kit] if isinstance(kit, str) else kit
    consignes = k.consignes + (f"\n\n{consignes_supplementaires}" if consignes_supplementaires else "")
    return Agent(modele, [*outils(connexion, list(k.outils)), *(outils_propres or [])], consignes,
                 trace=trace, messages=messages, **options)
