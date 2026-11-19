"""Modèles de langage branchés sur l'agent : aucun fournisseur imposé.

Un modèle est un objet qui, recevant la conversation et les outils, rend la réponse suivante :
du texte, ou des appels d'outils. `ModeleChat` couvre les API de chat au format OpenAI (Mistral,
OpenAI, serveurs locaux compatibles) ; un autre fournisseur s'ajoute en implémentant `Modele`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .erreurs import ErreurConfiguration, ServiceIndisponible
from .outils import Outil


@dataclass
class AppelOutil:
    id: str
    nom: str
    arguments: dict[str, Any]


@dataclass
class Tour:
    """Réponse du modèle à un tour : texte, ou appels d'outils à exécuter."""

    texte: str = ""
    appels: list[AppelOutil] = field(default_factory=list)
    brut: dict[str, Any] = field(default_factory=dict, repr=False)


class Modele(Protocol):
    def repondre(self, messages: list[dict[str, Any]], outils: list[Outil]) -> Tour:
        """`messages` au format OpenAI (system, user, assistant, tool)."""


def texte_de(contenu: Any) -> str:
    """Texte d'une réponse : chaîne, ou liste de blocs dont seuls les blocs `text` sont rendus
    (certains modèles y joignent des blocs de raisonnement)."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "".join(b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text")
    return ""


class ModeleChat:
    """API de chat au format OpenAI, avec outils.

    Défauts lus dans l'environnement : `REPERES_MODELE_URL` (https://api.mistral.ai/v1),
    `REPERES_MODELE_CLE` (sinon `MISTRAL_API_KEY`), `REPERES_MODELE` (mistral-large-latest)."""

    def __init__(self, url: str | None = None, cle: str | None = None, modele: str | None = None, *,
                 temperature: float = 0.2, timeout: float = 180):
        self.url = (url or os.getenv("REPERES_MODELE_URL") or "https://api.mistral.ai/v1").rstrip("/")
        self.cle = cle or os.getenv("REPERES_MODELE_CLE") or os.getenv("MISTRAL_API_KEY") or ""
        self.modele = modele or os.getenv("REPERES_MODELE") or "mistral-large-latest"
        self.temperature = temperature
        self.timeout = timeout
        if not self.cle:
            raise ErreurConfiguration("Clé du modèle absente : REPERES_MODELE_CLE ou MISTRAL_API_KEY.")

    def repondre(self, messages: list[dict[str, Any]], outils: list[Outil]) -> Tour:
        corps: dict[str, Any] = {"model": self.modele, "messages": messages, "temperature": self.temperature}
        if outils:
            corps.update(tools=[o.pour_openai() for o in outils], tool_choice="auto")
        req = Request(f"{self.url}/chat/completions", data=json.dumps(corps).encode(), method="POST",
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.cle}"})
        try:
            with urlopen(req, timeout=self.timeout) as r:
                m = json.load(r)["choices"][0]["message"]
        except HTTPError as e:
            raise ServiceIndisponible(f"Modèle : HTTP {e.code}.", statut_http=e.code) from None
        except (URLError, OSError, ValueError, KeyError, IndexError):
            raise ServiceIndisponible("Modèle injoignable ou réponse illisible.") from None
        appels = []
        for a in m.get("tool_calls") or []:
            f = a.get("function") or {}
            try:
                args = json.loads(f.get("arguments") or "{}")
            except ValueError:
                args = {}
            appels.append(AppelOutil(id=a.get("id") or "", nom=f.get("name", ""), arguments=args if isinstance(args, dict) else {}))
        return Tour(texte=texte_de(m.get("content")), appels=appels, brut=m)
