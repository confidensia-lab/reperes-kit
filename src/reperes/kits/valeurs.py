"""Instantané daté des valeurs d'Étalon (`etalon.instantane.v1`) et lecture par un calcul.

Un instantané contient, pour chaque paramètre utile, toutes ses valeurs datées avec leurs coordonnées
et leur source. Il se construit depuis l'API (`Instantane.depuis_api`), se sauve en JSON et se
recharge pour calculer hors ligne : même instantané, mêmes résultats au centime que le moteur REPERES.

    from reperes import Reperes
    from reperes.kits import autonomie
    from reperes.kits.valeurs import Instantane

    inst = Instantane.depuis_api(Reperes(), autonomie.PARAMETRES)
    inst.sauver("apa-2026-11.json")
    ...
    inst = Instantane.charger("apa-2026-11.json")
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from . import _dec

if TYPE_CHECKING:
    from ..client import Reperes

VERSION = "etalon.instantane.v1"


@dataclass
class ValeurEtalon:
    """Une valeur datée d'un paramètre."""

    valeur: str
    valide_du: str
    valide_au: str | None = None
    territoire: str | None = None
    coordonnees: dict[str, Any] = field(default_factory=dict)
    source: dict[str, str] | None = None
    passage: str | None = None

    @classmethod
    def depuis(cls, d: dict[str, Any]) -> "ValeurEtalon":
        src = d.get("source")
        source = None
        if isinstance(src, dict) and isinstance(src.get("titre"), str):
            source = {"titre": src["titre"]}
            for k in ("reference", "url"):
                if isinstance(src.get(k), str):
                    source[k] = src[k]
        return cls(
            valeur=_dec.texte(d["valeur"]),
            valide_du=str(d["valide_du"]),
            valide_au=d.get("valide_au") or None,
            territoire=d.get("territoire") or None,
            coordonnees=dict(d.get("coordonnees") or {}),
            source=source,
            passage=d.get("passage") or None,
        )

    def vers_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"valeur": self.valeur, "valide_du": self.valide_du}
        if self.valide_au:
            out["valide_au"] = self.valide_au
        if self.territoire:
            out["territoire"] = self.territoire
        if self.coordonnees:
            out["coordonnees"] = self.coordonnees
        if self.source:
            out["source"] = self.source
        if self.passage:
            out["passage"] = self.passage
        return out


class Instantane:
    """Séries des paramètres, par identifiant ; `lu_le` : date de lecture ; `origine` : d'où il vient."""

    def __init__(self, valeurs: dict[str, list[ValeurEtalon]] | None = None, *, lu_le: str | None = None,
                 origine: str | None = None):
        self.valeurs: dict[str, list[ValeurEtalon]] = valeurs or {}
        self.lu_le = lu_le
        self.origine = origine

    # Lecture --------------------------------------------------------------------------------

    def lire(self, parametre: str, coordonnees: Sequence[tuple[str, str]], date: str) -> ValeurEtalon | None:
        """Valeur nationale en vigueur à `date` pour exactement ces coordonnées (règle du moteur)."""
        retenue: ValeurEtalon | None = None
        for v in self.valeurs.get(parametre, []):
            if v.territoire not in (None, "nat_FR"):
                continue
            if len(v.coordonnees) != len(coordonnees):
                continue
            if not all(k in v.coordonnees and _dec.texte(v.coordonnees[k]) == c for k, c in coordonnees):
                continue
            if not (v.valide_du <= date and (v.valide_au is None or date < v.valide_au)):
                continue
            if retenue is None or v.valide_du >= retenue.valide_du:
                retenue = v
        return retenue

    # Fichier --------------------------------------------------------------------------------

    @classmethod
    def depuis_json(cls, d: dict[str, Any]) -> "Instantane":
        if d.get("schema_version") not in (None, VERSION):
            raise ValueError(f"Instantané de version inconnue : {d.get('schema_version')}.")
        valeurs = {k: [ValeurEtalon.depuis(x) for x in v] for k, v in (d.get("valeurs") or {}).items()}
        return cls(valeurs, lu_le=d.get("lu_le"), origine=d.get("origine"))

    @classmethod
    def charger(cls, chemin: str | Path) -> "Instantane":
        return cls.depuis_json(json.loads(Path(chemin).read_text(encoding="utf-8")))

    def vers_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schema_version": VERSION}
        if self.lu_le:
            out["lu_le"] = self.lu_le
        if self.origine:
            out["origine"] = self.origine
        out["valeurs"] = {k: [x.vers_json() for x in v] for k, v in sorted(self.valeurs.items())}
        return out

    def sauver(self, chemin: str | Path) -> None:
        Path(chemin).write_text(json.dumps(self.vers_json(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # API ------------------------------------------------------------------------------------

    @classmethod
    def depuis_api(cls, client: "Reperes", parametres: Iterable[str]) -> "Instantane":
        """Instantané des séries complètes (`historique`, tous territoires) des paramètres, lues sur l'API.

        Coûte une lecture de valeur par paramètre (franchise mensuelle)."""
        valeurs: dict[str, list[ValeurEtalon]] = {}
        for p in parametres:
            r = client.historique(p, territoire="*")
            valeurs[p] = [ValeurEtalon.depuis(v) for v in r.get("valeurs") or [] if isinstance(v, dict) and "valeur" in v]
        return cls(valeurs, lu_le=_dt.date.today().isoformat(), origine=f"{client.base_url}/api/v1/valeurs")


class Lecteur:
    """Lit l'instantané pendant un calcul et garde la trace des valeurs utilisées (champ `valeurs`)."""

    def __init__(self, instantane: Instantane):
        self.instantane = instantane
        self._utilisees: list[dict[str, Any]] = []

    def lire(self, parametre: str, coordonnees: Sequence[tuple[str, str]], date: str) -> tuple[Decimal, ValeurEtalon] | None:
        v = self.instantane.lire(parametre, coordonnees, date)
        if v is None:
            return None
        d = _dec.parse(v.valeur)
        if d is None:
            return None
        u: dict[str, Any] = {"parametre": parametre}
        if coordonnees:
            u["coordonnees"] = {k: c for k, c in coordonnees}
        u.update({"date": date, "valeur": v.valeur, "valide_du": v.valide_du})
        if v.source:
            u["source"] = dict(v.source)
        if u not in self._utilisees:
            self._utilisees.append(u)
        return d, v

    def valeur(self, parametre: str, coordonnees: Sequence[tuple[str, str]], date: str) -> Decimal | None:
        r = self.lire(parametre, coordonnees, date)
        return r[0] if r else None

    def utilisees(self) -> list[dict[str, Any]]:
        return [dict(u) for u in self._utilisees]
