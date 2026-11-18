"""Transport HTTP du client : bibliothèque standard seule, HTTPS exigé hors de la machine locale, aucune
redirection suivie (la clé ne quitte jamais l'origine), nouvelles tentatives sur un débit dépassé."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

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

LOCALES = {"localhost", "127.0.0.1", "::1"}
ATTENTE_MAX = 30


class _SansRedirection(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def verifier_url(base_url: str) -> str:
    """Origine HTTP(S) sans identifiants, requête ni fragment ; HTTPS hors de la machine locale."""
    try:
        url = urlsplit(base_url)
        valide = url.scheme in {"http", "https"} and bool(url.hostname) and url.port != 0
    except ValueError:
        valide = False
    if not valide or url.username or url.password or url.query or url.fragment:
        raise ErreurConfiguration("URL invalide : origine HTTP(S) attendue, sans identifiants, requête ni fragment.")
    if url.scheme == "http" and url.hostname not in LOCALES:
        raise ErreurConfiguration("HTTPS requis hors de la machine locale.")
    return base_url.rstrip("/")


def verifier_cle(cle: str) -> str:
    if not cle or any(ord(c) < 33 or ord(c) > 126 for c in cle):
        raise ErreurConfiguration("Clé API invalide.")
    return cle


@dataclass
class Reponse:
    statut: int
    entetes: dict[str, str]
    corps: Any


INDICES = {
    401: "clé absente ou invalide (REPERES_API_KEY)",
    402: "franchise du mois atteinte, crédits insuffisants",
    403: "opération hors de votre droit",
}


def _entier(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def erreur_http(statut: int, corps: Any, entetes: dict[str, str]) -> ErreurReperes:
    """Erreur typée depuis une réponse HTTP en échec ; message sans secret ni contenu."""
    c = corps if isinstance(corps, dict) else {}
    morceaux = [f"HTTP {statut}"]
    for cle in ("error", "detail", "credits_required", "credits_balance", "upgrade_url", "retry_after_seconds"):
        v = c.get(cle)
        if isinstance(v, (str, int)) and not isinstance(v, bool):
            morceaux.append(f"{cle}={v}")
    if isinstance(c.get("error"), dict) and isinstance(c["error"].get("code"), str):
        morceaux.append(f"code={c['error']['code']}")
    if statut in INDICES:
        morceaux.append(f"— {INDICES[statut]}")
    message = " ".join(morceaux)
    kw = dict(
        statut_http=statut,
        code=c.get("error") if isinstance(c.get("error"), str) else None,
        detail=c.get("detail") if isinstance(c.get("detail"), str) else None,
        upgrade_url=c.get("upgrade_url") if isinstance(c.get("upgrade_url"), str) else None,
    )
    if statut == 401:
        return ErreurAuthentification(message, **kw)
    if statut == 402:
        return CreditsEpuises(message, credits_requis=_entier(c.get("credits_required")), solde=_entier(c.get("credits_balance")), **kw)
    if statut == 403:
        return ErreurDroit(message, **kw)
    if statut == 429:
        attente = _entier(c.get("retry_after_seconds"))
        if attente is None and (entetes.get("retry-after") or "").isdigit():
            attente = int(entetes["retry-after"])
        return DebitDepasse(message, attente=attente, **kw)
    if statut >= 500:
        return ServiceIndisponible(message, **kw)
    return ErreurRequete(message, **kw)


class Transport:
    def __init__(self, base_url: str, *, cle: str | None, timeout: float, tentatives: int,
                 agent: str, dormir: Callable[[float], None] = time.sleep):
        self.base = verifier_url(base_url)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ErreurConfiguration("Le délai doit être un nombre positif.")
        self.cle = verifier_cle(cle) if cle else None
        self.timeout = timeout
        self.tentatives = max(0, tentatives)
        self.agent = agent
        self._dormir = dormir
        self._ouvreur = build_opener(_SansRedirection())

    def appeler(self, methode: str, chemin: str, corps: Any = None, *, authentifie: bool = True,
                statuts_resultat: frozenset[int] = frozenset()) -> Reponse:
        """Appel JSON. Un code de `statuts_resultat` (422 d'une simulation non couverte) rend son corps
        comme résultat ; les autres échecs lèvent une `ErreurReperes` typée."""
        if authentifie and not self.cle:
            raise ErreurConfiguration("REPERES_API_KEY absente : créez une clé sur la page de connexion MCP de REPERES.")
        entetes = {"Accept": "application/json", "User-Agent": self.agent}
        if authentifie and self.cle:
            entetes["Authorization"] = f"Bearer {self.cle}"
        donnees = None
        if corps is not None:
            entetes["Content-Type"] = "application/json"
            donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        essai = 0
        while True:
            req = Request(self.base + chemin, data=donnees, headers=entetes, method=methode)
            try:
                with self._ouvreur.open(req, timeout=self.timeout) as r:
                    return Reponse(r.status, {k.lower(): v for k, v in r.headers.items()}, _json(r.read()))
            except HTTPError as exc:
                statut = exc.code
                entetes_r = {k.lower(): v for k, v in (exc.headers or {}).items()}
                try:
                    brut = exc.read()
                finally:
                    exc.close()
                try:
                    corps_r = json.loads(brut.decode("utf-8")) if brut else None
                except (ValueError, UnicodeError):
                    corps_r = None
                if statut in statuts_resultat and isinstance(corps_r, dict):
                    return Reponse(statut, entetes_r, corps_r)
                erreur = erreur_http(statut, corps_r, entetes_r)
                if isinstance(erreur, DebitDepasse) and essai < self.tentatives:
                    essai += 1
                    self._dormir(min(ATTENTE_MAX, erreur.attente or 2 ** essai))
                    continue
                raise erreur from None
            except (URLError, OSError, TimeoutError):
                raise ServiceIndisponible("Service injoignable ou délai dépassé.") from None


def _json(brut: bytes) -> Any:
    try:
        return json.loads(brut.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ServiceIndisponible("Réponse JSON invalide.") from None
