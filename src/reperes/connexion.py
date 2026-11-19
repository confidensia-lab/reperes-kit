"""Connexion à REPERES : même interface, que REPERES soit atteint par l'API ou par la CLI.

    from reperes.connexion import ConnexionAPI, ConnexionCLI

    c = ConnexionAPI()                 # HTTP direct (clé REPERES_API_KEY)
    c = ConnexionCLI()                 # commande `reperes` installée (même clé, même résultat)
    c.executer("reperes_valeur", {"id": "smic.horaire", "date": "2026-03-01"})

La connexion CLI sert quand l'environnement de l'agent passe par des commandes (bac à sable, agent de
code piloté depuis un terminal, outil d'intégration) : elle appelle `reperes outil <nom>` et lit le
JSON rendu sur la sortie standard.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any, Protocol

from .client import Reperes
from ._http import erreur_http
from .erreurs import ErreurConfiguration, ErreurReperes, ServiceIndisponible
from .outils import OUTILS_FRAMEWORK, Outil, executer_par_api


class Connexion(Protocol):
    """Ce qu'un agent attend de REPERES : le catalogue des outils et leur exécution."""

    def definitions(self) -> list[dict[str, Any]]:
        """Définitions publiées des outils (nom, description, inputSchema, droit, credits)."""

    def executer(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Exécute un outil ; lève une `ErreurReperes` en cas d'échec."""


def outils(connexion: Connexion, noms: list[str] | None = None) -> list[Outil]:
    """Outils REPERES prêts pour un modèle, dans l'ordre de `noms` (tous si `None`)."""
    defs = {**OUTILS_FRAMEWORK, **{d["name"]: d for d in connexion.definitions()}}
    choisis = noms if noms is not None else list(defs)
    manquants = [n for n in choisis if n not in defs]
    if manquants:
        raise ErreurConfiguration(f"Outils absents du catalogue REPERES : {', '.join(manquants)}.")
    return [
        Outil(nom=n, description=defs[n].get("description", ""), schema=defs[n].get("inputSchema") or {"type": "object"},
              executer=lambda a, n=n: connexion.executer(n, a),
              lecture_seule=(defs[n].get("annotations") or {}).get("readOnlyHint"))
        for n in choisis
    ]


class ConnexionAPI:
    """REPERES par l'API HTTP (client `Reperes`)."""

    def __init__(self, client: Reperes | None = None):
        self.client = client or Reperes()
        self._definitions: list[dict[str, Any]] | None = None

    def definitions(self) -> list[dict[str, Any]]:
        if self._definitions is None:
            self._definitions = self.client.outils_mcp()
        return self._definitions

    def executer(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return executer_par_api(self.client, nom, arguments)


class ConnexionCLI:
    """REPERES par la commande `reperes` (même paquet, installé dans l'environnement de l'agent).

    `commande` : chemin ou nom de la commande (défaut : `reperes`, sinon `python -m reperes`) ;
    `env` : variables transmises (défaut : celles du processus, dont REPERES_API_KEY)."""

    def __init__(self, commande: str | list[str] | None = None, *, env: dict[str, str] | None = None, timeout: float = 240):
        if commande is None:
            commande = ["reperes"] if shutil.which("reperes") else [sys.executable, "-m", "reperes"]
        self.commande = [commande] if isinstance(commande, str) else list(commande)
        self.env = env
        self.timeout = timeout
        self._definitions: list[dict[str, Any]] | None = None

    def _lancer(self, arguments: list[str], entree: str | None = None) -> Any:
        try:
            p = subprocess.run([*self.commande, *arguments], input=entree, capture_output=True, text=True,
                               timeout=self.timeout, env=self.env if self.env is not None else os.environ.copy())
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ServiceIndisponible(f"Commande reperes indisponible : {type(e).__name__}.") from None
        sortie = p.stdout.strip()
        # Code 3 : résultat dégradé, rendu sur stdout comme un résultat.
        if p.returncode != 0 and not sortie:
            raise _erreur_cli(p.stderr.strip(), p.returncode)
        try:
            return json.loads(sortie)
        except ValueError:
            raise ServiceIndisponible("Sortie de la commande reperes illisible.") from None

    def definitions(self) -> list[dict[str, Any]]:
        if self._definitions is None:
            d = self._lancer(["outils", "--erreurs-json"])
            self._definitions = list(d) if isinstance(d, list) else []
        return self._definitions

    def executer(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Arguments sur l'entrée standard : aucun échappement de shell, rien dans la liste des processus.
        r = self._lancer(["outil", nom, "--arguments", "-", "--erreurs-json"], entree=json.dumps(arguments or {}, ensure_ascii=False))
        return r if isinstance(r, dict) else {"donnees": r}


def _erreur_cli(stderr: str, code: int) -> ErreurReperes:
    """Erreur typée depuis la sortie d'erreur JSON de `reperes … --erreurs-json`."""
    try:
        e = json.loads(stderr.splitlines()[-1]) if stderr else {}
    except ValueError:
        e = {}
    if isinstance(e, dict) and isinstance(e.get("statut_http"), int):
        corps = {"error": e.get("error"), "detail": e.get("detail"), "upgrade_url": e.get("upgrade_url"),
                 "credits_required": e.get("credits_requis"), "credits_balance": e.get("solde"),
                 "retry_after_seconds": e.get("attente")}
        return erreur_http(e["statut_http"], {k: v for k, v in corps.items() if v is not None}, {})
    message = e.get("message") if isinstance(e, dict) and e.get("message") else stderr
    if isinstance(e, dict) and e.get("error") == "ErreurConfiguration":
        return ErreurConfiguration(message)
    return ErreurReperes(message or f"reperes : code de sortie {code}.")
