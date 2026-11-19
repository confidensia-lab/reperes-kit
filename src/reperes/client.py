"""Client de l'API REPERES.

    from reperes import Reperes

    client = Reperes()                       # clé lue dans REPERES_API_KEY
    smic = client.valeur("smic.horaire", date="2026-03-01")
    print(smic["valeurs"][0]["valeur"], smic.operation_id)

Chaque méthode rend un `Resultat` : le JSON de la réponse (un `dict`, au contrat déclaré dans
`schema_version`), avec l'identifiant de l'opération comptée et, si elle a été payée en crédits, le
nombre de crédits débités et le solde. Contrats : https://reperes.bmse.fr/docs/contrats
"""
from __future__ import annotations

import os
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from ._http import Reponse, Transport
from .erreurs import ErreurConfiguration

URL_PAR_DEFAUT = "https://mcp.reperes.bmse.fr"
NON_COUVERT = frozenset({422})


class Resultat(dict):
    """Réponse JSON de l'API, avec les métadonnées de l'opération.

    `operation_id` : identifiant de l'opération comptée, à communiquer au support ;
    `credits_debites`, `credits_restants` : quand l'opération dépasse la franchise du mois ;
    `statut_http` : 200, ou 422 pour une simulation non couverte (le résultat dit pourquoi).
    """

    operation_id: str | None
    credits_debites: int | None
    credits_restants: int | None
    statut_http: int

    @classmethod
    def depuis(cls, r: Reponse) -> "Resultat":
        corps = r.corps if isinstance(r.corps, dict) else {"donnees": r.corps}
        res = cls(corps)
        res.statut_http = r.statut
        res.operation_id = r.entetes.get("x-reperes-operation-id")
        res.credits_debites = _entier(r.entetes.get("x-reperes-credits-charged"))
        res.credits_restants = _entier(r.entetes.get("x-reperes-credits-remaining"))
        return res

    @property
    def contrat(self) -> str | None:
        """Contrat de la réponse (`schema_version`), ex. `calcul.esat.v1`."""
        v = self.get("schema_version")
        return v if isinstance(v, str) else None


def _entier(v: str | None) -> int | None:
    return int(v) if v and v.isdigit() else None


def _requete(params: list[tuple[str, str]]) -> str:
    return "?" + urlencode(params) if params else ""


def _coordonnees(date: str | None, territoire: str | None, coordonnees: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    p: list[tuple[str, str]] = []
    if date:
        p.append(("date", date))
    if territoire:
        p.append(("territoire", territoire))
    for k, v in (coordonnees or {}).items():
        p.append((str(k), str(v)))
    return p


class Reperes:
    """Client de l'API REPERES.

    `api_key` : clé `rpr_sk_…` (défaut : variable `REPERES_API_KEY`), créée sur la page de connexion
    MCP de REPERES ; `base_url` (défaut : `REPERES_API_URL`, puis l'API publique) ; `timeout` en
    secondes ; `tentatives` : nouvelles tentatives sur un débit dépassé (429), en respectant
    `Retry-After`.
    """

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 180,
                 tentatives: int = 2):
        from . import __version__

        cle = (api_key if api_key is not None else os.getenv("REPERES_API_KEY", "")).strip() or None
        self._t = Transport(
            base_url or os.getenv("REPERES_API_URL") or URL_PAR_DEFAUT,
            cle=cle, timeout=timeout, tentatives=tentatives, agent=f"reperes-python/{__version__}",
        )

    @property
    def base_url(self) -> str:
        """Adresse de l'API utilisée par le client."""
        return self._t.base

    # Contexte et réponses -------------------------------------------------------------------

    def context(self, question: str, *, exploration: bool = False) -> Resultat:
        """Contexte sourcé (doctrine, actualité, preuves, statistiques) d'une question ; l'appelant rédige."""
        corps: dict[str, Any] = {"query": _question(question)}
        if exploration:
            corps["exploration"] = True
        return self._post("/api/v1/context", corps)

    def precision(self, question: str) -> Resultat:
        """Information ponctuelle et citation vérifiée, ou statut `not_found`, `depends`, `out_of_scope`."""
        return self._post("/api/v1/precision", {"query": _question(question)})

    def answer(self, question: str) -> Resultat:
        """Réponse rédigée par REPERES, avec ses sources (option Génération ou crédits)."""
        return self._post("/api/v1/answer", {"query": _question(question)})

    # Valeurs de référence --------------------------------------------------------------------

    def valeur(self, parametre: str, *, date: str | None = None, territoire: str | None = None,
               coordonnees: Mapping[str, Any] | None = None) -> Resultat:
        """Valeur applicable d'un paramètre (`smic.horaire`, `apa.domicile.plafond` avec `{"gir": 1}`…)."""
        chemin = "/api/v1/valeurs/" + quote(_identifiant(parametre), safe="")
        return self._get(chemin + _requete(_coordonnees(date, territoire, coordonnees)))

    def historique(self, parametre: str, *, territoire: str | None = None,
                   coordonnees: Mapping[str, Any] | None = None) -> Resultat:
        """Valeurs successives d'un paramètre (`territoire="*"` : tous les territoires)."""
        chemin = "/api/v1/valeurs/" + quote(_identifiant(parametre), safe="") + "/historique"
        return self._get(chemin + _requete(_coordonnees(None, territoire, coordonnees)))

    def resoudre(self, question: str, *, date: str | None = None, territoire: str | None = None,
                 coordonnees: Mapping[str, Any] | None = None) -> Resultat:
        """Valeur du paramètre qui répond à une question en français (`ambiguous` et candidats sinon)."""
        params = [("q", _question(question)), ("resoudre", "1"), *_coordonnees(date, territoire, coordonnees)]
        return self._get("/api/v1/valeurs" + _requete(params))

    def rechercher(self, q: str | None = None, *, famille: str | None = None) -> Resultat:
        """Paramètres candidats (recherche `q`) ou catalogue d'une famille, sans valeur."""
        params = [(k, v) for k, v in (("q", q), ("famille", famille)) if v]
        return self._get("/api/v1/valeurs" + _requete(params))

    # Simulateurs -----------------------------------------------------------------------------

    def remuneration(self, profil: Mapping[str, Any]) -> Resultat:
        """Simulation de rémunération CCN 66 ou CCN 51 (`calcul.remuneration.v1`)."""
        return self._post("/api/v1/calcul/remuneration", dict(profil), statuts_resultat=NON_COUVERT)

    def modeles(self) -> Resultat:
        """Conventions, emplois, éléments variables et types d'établissement (`calcul.modeles.v1`)."""
        return self._get("/api/v1/calcul/modeles")

    def trajectoire(self, demande: Mapping[str, Any]) -> Resultat:
        """Trajectoire d'une rémunération en euros courants et constants (`calcul.trajectoire.v1`)."""
        return self._post("/api/v1/calcul/trajectoire", dict(demande), statuts_resultat=NON_COUVERT)

    def esat(self, demande: Mapping[str, Any]) -> Resultat:
        """Rémunération garantie d'un travailleur d'ESAT (`calcul.esat.v1`)."""
        return self._post("/api/v1/calcul/esat", dict(demande), statuts_resultat=NON_COUVERT)

    def autonomie(self, scenario: Mapping[str, Any]) -> Resultat:
        """Démonstrateur APA à domicile : plan d'aide et reste à charge d'un mois (`calcul.autonomie.v1`).

        Accepte un cas de référence (`{"entree": {...}}`) : son entrée est envoyée."""
        sc = scenario.get("entree") if isinstance(scenario.get("entree"), Mapping) else scenario
        return self._post("/api/v1/calcul/autonomie", dict(sc), statuts_resultat=NON_COUVERT)

    # Publics : sources, contrats, description de l'API ---------------------------------------

    def source(self, identifiant: str, *, contenu: bool = False) -> Resultat:
        """Passeport de preuve d'un document cité (`sources[].id`), avec son texte si `contenu`."""
        if not identifiant.strip():
            raise ErreurConfiguration("Identifiant de source vide.")
        chemin = "/sources/" + quote(identifiant.strip(), safe="") + ("/content" if contenu else "")
        return self._get(chemin, authentifie=False)

    def openapi(self) -> Resultat:
        """Description OpenAPI de l'API."""
        return self._get("/api/v1/openapi.json", authentifie=False)

    def contrats(self) -> list[dict[str, Any]]:
        """Contrats de réponse publiés : nom, titre, description, adresse du schéma."""
        r = self._t.appeler("GET", "/api/v1/schemas", authentifie=False)
        return list(r.corps) if isinstance(r.corps, list) else []

    def schema(self, contrat: str) -> Resultat:
        """Schéma JSON d'un contrat (`calcul.esat.v1`…)."""
        return self._get(f"/api/v1/schemas/{quote(_identifiant(contrat), safe='')}.json", authentifie=False)

    # -----------------------------------------------------------------------------------------

    def _get(self, chemin: str, *, authentifie: bool = True) -> Resultat:
        return Resultat.depuis(self._t.appeler("GET", chemin, authentifie=authentifie))

    def _post(self, chemin: str, corps: dict[str, Any], *, statuts_resultat: frozenset[int] = frozenset()) -> Resultat:
        return Resultat.depuis(self._t.appeler("POST", chemin, corps, statuts_resultat=statuts_resultat))


def _question(q: str) -> str:
    q = (q or "").strip()
    if not q:
        raise ErreurConfiguration("La question est vide.")
    return q


def _identifiant(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ErreurConfiguration("Identifiant vide.")
    return v
