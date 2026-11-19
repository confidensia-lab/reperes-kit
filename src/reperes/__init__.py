"""REPERES : framework Python pour construire des agents et des outils sur REPERES (champ social et
médico-social), et client de son API.

- `Reperes` : client de l'API (contexte sourcé, précision, valeurs de référence, simulateurs).
- `reperes.connexion` : REPERES par l'API ou par la commande `reperes`, même interface.
- `reperes.outils`, `reperes.agent`, `reperes.modeles` : outils pour modèles, boucle d'agent avec
  garde-fou de sourçage, modèles compatibles OpenAI (Mistral par défaut).
- `reperes.kits` : agents métier prêts à l'emploi (APA à domicile, rémunération, ESAT).

Documentation : https://reperes.bmse.fr/docs
"""
from __future__ import annotations

__version__ = "0.3.0"

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
