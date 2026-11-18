"""REPERES : SDK Python et CLI de l'API REPERES (champ social et médico-social).

Contexte documentaire sourcé, information ponctuelle vérifiée, valeurs de référence datées et
sourcées, simulateurs (rémunération conventionnelle, ESAT, trajectoire, APA à domicile) et réponses
rédigées. Documentation : https://reperes.bmse.fr/docs
"""
from __future__ import annotations

__version__ = "0.1.0"

from .client import URL_PAR_DEFAUT, Reperes, Resultat
from .erreurs import (
    CreditsEpuises,
    DebitDepasse,
    ErreurAuthentification,
    ErreurConfiguration,
    ErreurDroit,
    ErreurReperes,
    ErreurRequete,
    ServiceIndisponible,
)

__all__ = [
    "Reperes",
    "Resultat",
    "URL_PAR_DEFAUT",
    "ErreurReperes",
    "ErreurConfiguration",
    "ErreurRequete",
    "ErreurAuthentification",
    "ErreurDroit",
    "CreditsEpuises",
    "DebitDepasse",
    "ServiceIndisponible",
    "__version__",
]
