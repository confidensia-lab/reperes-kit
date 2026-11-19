"""APA à domicile : du besoin au plan d'aide, reste à charge d'un mois (contrat `calcul.autonomie.v1`).

Aide humaine d'un service autonomie à domicile prestataire. Le calcul part d'un scénario (faits avec
leur provenance : déclaration, notification ou facture transcrites, hypothèse) et d'un instantané des
valeurs d'Étalon. Il rend les contrôles d'orientation, le plafond du GIR à part du plan, le taux de
participation (notifié, ou calculé selon CASF R. 232-11 sur le plan accepté), la décomposition du mois,
les écarts d'heures et les informations manquantes dans l'ordre où elles débloquent le calcul. Un
montant inconnu reste `None` (`null`), avec son motif ; aucun GIR, aucun volume d'heures n'est déduit.

    from reperes.kits import autonomie
    from reperes.kits.valeurs import Instantane

    r = autonomie.calculer(scenario, Instantane.charger("apa-2026-01.json"))
    r["financement"]["reste_avant_fiscalite"]

Le résultat est le dict JSON que rend le moteur REPERES pour le même scénario et le même instantané,
au caractère près. Les opérations décimales reproduisent celles du moteur (voir `fois`, `divise`).
"""
from __future__ import annotations

import datetime as _dt

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from . import _dec
from .valeurs import Instantane, Lecteur

SCHEMA = "calcul.autonomie.v1"

#: Paramètres d'Étalon lus par le calcul.
PARAMETRES = [
    "mtp.mensuelle", "apa.domicile.plafond", "apa.domicile.plafond.majoration", "apa.domicile.participation.coefficient",
    "apa.domicile.participation.fraction.coefficient", "apa.non_versement.seuil", "sad.tarif_minimal",
    "credit_impot.emploi_domicile.taux",
]

R232_11 = "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000038681713"
L232_4 = "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000031726947"
D232_31 = "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006905647"
L245_9 = "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006797122"
D232_17_1 = "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000049488542"
#: Entrée en vigueur de la période de référence de six mois (report des heures, D. 232-17-1).
REPORT_DEPUIS = "2024-05-01"

#: Signalements permanents du démonstrateur.
AVERTISSEMENTS = [
    "Simulation non opposable : la décision appartient au département (APA) ; elle prépare un entretien, la lecture d'une facture ou une demande de réévaluation.",
]

ZERO = Decimal(0)


class ScenarioInvalide(ValueError):
    """Scénario illisible (champ de mauvais type, nombre illisible, date absente) : rien n'est calculé."""


# ─────────────────────────── Décimal du moteur ───────────────────────────
#
# Le moteur calcule en décimal à mantisse de 96 bits et au plus 28 décimales. Une addition ou une
# multiplication est exacte tant que le résultat tient dans ce format ; sinon elle est arrondie au
# pair le plus proche au nombre de décimales qui tient. Une division non exacte garde le plus de
# décimales possible (jusqu'à 28, mantisse sous 2^96), arrondie au pair. Le décimal Python à 28
# chiffres significatifs arrondit autrement (un 29e chiffre tient parfois dans 96 bits) : les quatre
# opérations ci-dessous reproduisent celles du moteur, en entiers exacts.

_U96 = 1 << 96
_ECHELLE_MAX = 28


def _parts(d: Decimal) -> tuple[bool, int, int]:
    """(négatif, mantisse, échelle) d'un décimal fini."""
    signe, chiffres, exp = d.as_tuple()
    m = int("".join(map(str, chiffres)) or "0")
    if exp > 0:
        m *= 10 ** exp
        exp = 0
    return bool(signe), m, -exp


def _decimal(negatif: bool, m: int, echelle: int) -> Decimal:
    return Decimal((1 if negatif and m else 0, tuple(int(c) for c in str(m)), -echelle))


def _ajuste(negatif: bool, m: int, echelle: int) -> Decimal:
    """Résultat exact ramené au format du moteur : échelle ≤ 28, mantisse < 2^96, demi au pair."""
    k = max(0, echelle - _ECHELLE_MAX)
    while m // 10 ** k >= _U96:
        k += 1
    if k:
        if k > echelle:
            raise OverflowError("dépassement de capacité du décimal")
        q, r = divmod(m, 10 ** k)
        demi = 5 * 10 ** (k - 1)
        if r > demi or (r == demi and q & 1):
            q += 1
        m, echelle = q, echelle - k
    return _decimal(negatif, m, echelle)


def plus(a: Decimal, b: Decimal) -> Decimal:
    """a + b comme le moteur."""
    na, ma, sa = _parts(a)
    nb, mb, sb = _parts(b)
    s = max(sa, sb)
    v = (-1 if na else 1) * ma * 10 ** (s - sa) + (-1 if nb else 1) * mb * 10 ** (s - sb)
    return _ajuste(v < 0, abs(v), s)


def moins(a: Decimal, b: Decimal) -> Decimal:
    """a − b comme le moteur."""
    return plus(a, -b)


def fois(a: Decimal, b: Decimal) -> Decimal:
    """a × b comme le moteur."""
    na, ma, sa = _parts(a)
    nb, mb, sb = _parts(b)
    if ma == 0 or mb == 0:
        return ZERO
    return _ajuste(na != nb, ma * mb, sa + sb)


def divise(a: Decimal, b: Decimal) -> Decimal:
    """a ÷ b comme le moteur : exact s'il tombe juste, sinon au plus de décimales possible, demi au pair."""
    na, ma, sa = _parts(a)
    nb, mb, sb = _parts(b)
    if mb == 0:
        raise ZeroDivisionError("division par zéro")
    if ma == 0:
        return ZERO
    negatif = na != nb
    debut = max(sa - sb, 0)
    s = _ECHELLE_MAX
    for e in range(debut, _ECHELLE_MAX + 1):
        q, r = divmod(ma * 10 ** (e - sa + sb), mb)
        if q >= _U96:
            if e == debut:
                raise OverflowError("dépassement de capacité du décimal")
            s = e - 1
            break
        if r == 0:
            return _decimal(negatif, q, e)
    q, r = divmod(ma * 10 ** (s - sa + sb), mb)
    if 2 * r > mb or (2 * r == mb and q & 1):
        q += 1
    return _decimal(negatif, q, s)


def somme(valeurs: list[Decimal]) -> Decimal:
    """Somme comme le moteur (additions successives depuis zéro)."""
    t = ZERO
    for v in valeurs:
        t = plus(t, v)
    return t


def arrondi_pair(d: Decimal, decimales: int) -> Decimal:
    """`round_dp` du moteur : au plus `decimales` décimales, demi au pair."""
    _, _, echelle = _parts(d)
    if echelle <= decimales:
        return d
    with localcontext() as c:
        c.prec = 60
        return d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_EVEN)


def pct(d: Decimal) -> Decimal:
    """Pourcentage → fraction (20 → 0,2)."""
    return divise(d, _dec.CENT)


# ─────────────────────────── Entrée ───────────────────────────

PROVENANCES = {
    "declaration": "Déclaré",
    "notification": "Notification (transcrite)",
    "facture": "Facture (transcrite)",
    "hypothese": "Hypothèse modifiable",
}


def _objet(d: dict, cle: str, chemin: str) -> dict | None:
    if cle not in d or d[cle] is None:
        return None
    v = d[cle]
    if not isinstance(v, dict):
        raise ScenarioInvalide(f"{chemin}{cle} : objet attendu")
    return v


def _nombre(d: dict, cle: str, chemin: str) -> Decimal | None:
    """Champ numérique : texte (« 24 », « 26,50 ») ou nombre ; absent, `null` ou texte vide → `None`."""
    v = d.get(cle)
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    n = _dec.valeur(v)
    if n is None:
        raise ScenarioInvalide(f"{chemin}{cle} : nombre attendu : {v!r}")
    return n


def _entier(d: dict, cle: str, chemin: str, maximum: int) -> int | None:
    v = d.get(cle)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= maximum:
        raise ScenarioInvalide(f"{chemin}{cle} : entier de 0 à {maximum} attendu")
    return v


def _booleen(d: dict, cle: str, chemin: str) -> bool | None:
    v = d.get(cle)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise ScenarioInvalide(f"{chemin}{cle} : booléen attendu")
    return v


def _drapeau(d: dict, cle: str, chemin: str) -> bool:
    """Booléen non optionnel : absent → faux ; `null` refusé."""
    if cle not in d:
        return False
    v = d[cle]
    if not isinstance(v, bool):
        raise ScenarioInvalide(f"{chemin}{cle} : booléen attendu")
    return v


def _texte(d: dict, cle: str, chemin: str) -> str | None:
    v = d.get(cle)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ScenarioInvalide(f"{chemin}{cle} : texte attendu")
    return v


def _provenance(d: dict, chemin: str) -> str:
    if "provenance" not in d:
        return "hypothese"
    v = d["provenance"]
    if v not in PROVENANCES:
        raise ScenarioInvalide(f"{chemin}provenance : {', '.join(PROVENANCES)} attendu")
    return v


@dataclass
class Personne:
    age: int | None = None
    #: GIR communiqué (1 à 6), jamais déduit.
    gir: int | None = None
    domicile: bool | None = None
    pch_accordee: bool | None = None
    provenance: str = "hypothese"


@dataclass
class AideHumaine:
    #: Heures mensuelles prévues par le plan.
    heures: Decimal | None = None
    #: Tarif horaire de prise en charge par le département.
    tarif: Decimal | None = None


@dataclass
class Poste:
    libelle: str
    montant: Decimal | None = None


@dataclass
class Plan:
    #: `notifie`, `propose` ou `envisage`.
    statut: str | None = None
    aide_humaine: AideHumaine | None = None
    #: Autres postes mensuels du plan accepté (aides techniques, accueil de jour…).
    autres_postes: list[Poste] = field(default_factory=list)
    #: Taux de participation notifié, en %.
    taux_participation: Decimal | None = None
    #: APA et participation forfaitaires (CASF L. 232-4, alinéa 3).
    forfait: bool = False
    provenance: str = "hypothese"


@dataclass
class Ressources:
    #: Ressources mensuelles retenues (du couple si `couple`).
    mensuelles: Decimal | None = None
    #: Couple résidant conjointement à domicile : ressources du couple divisées par 1,7.
    couple: bool = False
    provenance: str = "hypothese"


@dataclass
class Realise:
    heures_dans_plan: Decimal | None = None
    heures_hors_plan: Decimal | None = None
    #: Tarif horaire facturé par le service.
    prix_horaire: Decimal | None = None
    #: Facture déjà nette de l'APA versée au service (tiers payant).
    facture_nette_apa: bool = False
    provenance: str = "hypothese"


@dataclass
class Besoin:
    heures_estimees: Decimal | None = None
    provenance: str = "hypothese"


@dataclass
class Fiscal:
    #: Dépenses payées par le contribuable et éligibles (services à la personne).
    eligible: bool | None = None
    #: Part du plafond annuel des dépenses encore disponible.
    plafond_disponible: Decimal | None = None


@dataclass
class Scenario:
    #: Date de lecture des barèmes (AAAA-MM-JJ), en général dans le mois considéré.
    date: str
    #: Mois considéré (AAAA-MM).
    periode: str | None = None
    personne: Personne = field(default_factory=Personne)
    plan: Plan | None = None
    ressources: Ressources | None = None
    realise: Realise | None = None
    besoin: Besoin | None = None
    fiscal: Fiscal | None = None


def lire_scenario(d: Any) -> Scenario:
    """Scénario lu comme le moteur : champs optionnels, nombres en texte ou en nombre.

    Lève `ScenarioInvalide` si un champ n'a pas le type attendu."""
    if not isinstance(d, dict):
        raise ScenarioInvalide("scénario : objet attendu")
    # Date absente : aujourd'hui, comme l'API.
    date = d.get("date", _dt.date.today().isoformat())
    if not isinstance(date, str):
        raise ScenarioInvalide("date : texte AAAA-MM-JJ attendu")
    s = Scenario(date=date, periode=_texte(d, "periode", ""))

    if "personne" in d:
        p = d["personne"]
        if not isinstance(p, dict):
            raise ScenarioInvalide("personne : objet attendu")
        c = "personne."
        s.personne = Personne(age=_entier(p, "age", c, 2 ** 32 - 1), gir=_entier(p, "gir", c, 255),
                              domicile=_booleen(p, "domicile", c), pch_accordee=_booleen(p, "pch_accordee", c),
                              provenance=_provenance(p, c))

    p = _objet(d, "plan", "")
    if p is not None:
        c = "plan."
        a = _objet(p, "aide_humaine", c)
        aide = None if a is None else AideHumaine(heures=_nombre(a, "heures", c + "aide_humaine."),
                                                   tarif=_nombre(a, "tarif", c + "aide_humaine."))
        postes: list[Poste] = []
        if "autres_postes" in p:
            if not isinstance(p["autres_postes"], list):
                raise ScenarioInvalide("plan.autres_postes : liste attendue")
            for i, x in enumerate(p["autres_postes"]):
                ci = f"plan.autres_postes[{i}]."
                if not isinstance(x, dict) or not isinstance(x.get("libelle"), str):
                    raise ScenarioInvalide(f"{ci}libelle : texte attendu")
                postes.append(Poste(libelle=x["libelle"], montant=_nombre(x, "montant", ci)))
        s.plan = Plan(statut=_texte(p, "statut", c), aide_humaine=aide, autres_postes=postes,
                      taux_participation=_nombre(p, "taux_participation", c), forfait=_drapeau(p, "forfait", c),
                      provenance=_provenance(p, c))

    r = _objet(d, "ressources", "")
    if r is not None:
        c = "ressources."
        s.ressources = Ressources(mensuelles=_nombre(r, "mensuelles", c), couple=_drapeau(r, "couple", c),
                                  provenance=_provenance(r, c))

    r = _objet(d, "realise", "")
    if r is not None:
        c = "realise."
        s.realise = Realise(heures_dans_plan=_nombre(r, "heures_dans_plan", c),
                            heures_hors_plan=_nombre(r, "heures_hors_plan", c),
                            prix_horaire=_nombre(r, "prix_horaire", c),
                            facture_nette_apa=_drapeau(r, "facture_nette_apa", c), provenance=_provenance(r, c))

    b = _objet(d, "besoin", "")
    if b is not None:
        s.besoin = Besoin(heures_estimees=_nombre(b, "heures_estimees", "besoin."), provenance=_provenance(b, "besoin."))

    f = _objet(d, "fiscal", "")
    if f is not None:
        s.fiscal = Fiscal(eligible=_booleen(f, "eligible", "fiscal."),
                          plafond_disponible=_nombre(f, "plafond_disponible", "fiscal."))
    return s


# ─────────────────────────── Participation (R. 232-11) ───────────────────────────

@dataclass(frozen=True)
class Bareme:
    """Barème de la participation à une date : MTP de référence et coefficients du texte."""

    #: MTP mensuelle en vigueur au 1er janvier.
    mtp: Decimal
    #: Seuils de ressources (0,725 et 2,67).
    seuil_bas: Decimal
    seuil_haut: Decimal
    #: Bornes des fractions du plan (0,317 et 0,498).
    borne_1: Decimal
    borne_2: Decimal


def fractions(a: Decimal, b: Bareme) -> tuple[Decimal, Decimal, Decimal]:
    """Fractions A1, A2, A3 du plan accepté `a`."""
    f1, f2 = fois(b.borne_1, b.mtp), fois(b.borne_2, b.mtp)
    a1 = max(min(a, f1), ZERO)
    a2 = min(max(moins(a, f1), ZERO), moins(f2, f1))
    a3 = max(moins(a, f2), ZERO)
    return a1, a2, a3


def participation_plan(a: Decimal, r: Decimal, b: Bareme) -> Decimal:
    """Participation P calculée sur le plan accepté `a` pour des ressources mensuelles `r`, non arrondie."""
    bas, haut = fois(b.seuil_bas, b.mtp), fois(b.seuil_haut, b.mtp)
    neuf = Decimal("0.9")
    if a <= ZERO or r <= bas:
        return ZERO
    if r > haut:
        return fois(neuf, a)
    x = divise(moins(r, bas), moins(haut, bas))
    a1, a2, a3 = fractions(a, b)
    poids_2 = plus(Decimal("0.4"), fois(Decimal("0.6"), x))
    poids_3 = plus(Decimal("0.2"), fois(Decimal("0.8"), x))
    return fois(fois(neuf, x), plus(plus(a1, fois(a2, poids_2)), fois(a3, poids_3)))


def taux(a: Decimal, r: Decimal, b: Bareme) -> Decimal:
    """Taux T = P / A (0 pour un plan nul)."""
    return ZERO if a <= ZERO else divise(participation_plan(a, r, b), a)


def bareme(lecteur: Lecteur, debut_annee: str) -> Bareme | None:
    """Barème de participation au 1er janvier de l'année ; `None` dès qu'une valeur manque."""
    lectures = [
        ("mtp.mensuelle", []),
        ("apa.domicile.participation.coefficient", [("seuil", "exoneration")]),
        ("apa.domicile.participation.coefficient", [("seuil", "plein_taux")]),
        ("apa.domicile.participation.fraction.coefficient", [("borne", "a1_a2")]),
        ("apa.domicile.participation.fraction.coefficient", [("borne", "a2_a3")]),
    ]
    v: list[Decimal] = []
    for parametre, coordonnees in lectures:
        d = lecteur.valeur(parametre, coordonnees, debut_annee)
        if d is None:
            return None
        v.append(d)
    return Bareme(*v)


# ─────────────────────────── Sortie ───────────────────────────

def _source(titre: str | None = None, url: str | None = None, parametre: str | None = None) -> dict[str, str]:
    s: dict[str, str] = {}
    if titre is not None:
        s["titre"] = titre
    if url is not None:
        s["url"] = url
    if parametre is not None:
        s["parametre"] = parametre
    return s


def _provenance_source(provenance: str) -> dict[str, str]:
    return _source(titre=PROVENANCES[provenance])


def _loi(titre: str, url: str) -> dict[str, str]:
    return _source(titre=titre, url=url)


def _parametre(identifiant: str) -> dict[str, str]:
    return _source(parametre=identifiant)


class _Ligne:
    """Ligne de calcul ; sérialisée avec les champs absents omis."""

    __slots__ = ("id", "libelle", "base", "taux", "unite", "montant", "source", "hypothese")

    def __init__(self, id: str, libelle: str, montant: Decimal):
        self.id, self.libelle = id, libelle
        self.base: str | None = None
        self.taux: str | None = None
        self.unite: str | None = None
        self.montant = _dec.montant(montant)
        self.source: dict[str, str] | None = None
        self.hypothese: str | None = None

    def vers_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "libelle": self.libelle}
        for k in ("base", "taux", "unite"):
            if getattr(self, k) is not None:
                out[k] = getattr(self, k)
        out["montant"] = self.montant
        if self.source is not None:
            out["source"] = self.source
        if self.hypothese is not None:
            out["hypothese"] = self.hypothese
        return out


def _controle(id: str, libelle: str, statut: str, detail: str | None = None) -> dict[str, str]:
    c = {"id": id, "libelle": libelle, "statut": statut}
    if detail is not None:
        c["detail"] = detail
    return c


FINANCEMENT = ("plan_accepte", "facture_brute", "base_utilisee", "taux_participation", "participation", "apa_estimee",
               "depassement", "hors_plan", "reste_avant_fiscalite", "credit_impot_potentiel", "cout_net_fiscal_potentiel")
HEURES = ("besoin_estime", "prevues", "realisees_dans_plan", "non_realisees", "hors_plan")


def _resultat(date: str, periode: str | None) -> dict[str, Any]:
    r: dict[str, Any] = {"schema_version": SCHEMA, "statut": "ok", "date": date}
    if periode is not None:
        r["periode"] = periode
    r.update({
        "controles": [], "plafond": [], "participation": [], "mois": [],
        "financement": {k: None for k in FINANCEMENT}, "heures": {k: None for k in HEURES},
        "indisponibles": [], "informations_manquantes": [], "signalements": [], "valeurs": [],
    })
    return r


def _erreur(date: str, message: str) -> dict[str, Any]:
    r = _resultat(date, None)
    r["statut"] = "erreur"
    return {"schema_version": r.pop("schema_version"), "statut": r.pop("statut"), "message": message, **r}


def euros(d: Decimal) -> str:
    """« 1 234,56 € »."""
    return f"{_dec.fr(d, 2)} €"


def h(d: Decimal) -> str:
    """Heures : « 20 h », « 20,50 h »."""
    n = d.normalize()
    return f"{_dec.fr(n, 0 if n.as_tuple().exponent >= 0 else 2)} h"


def date_valide(d: str) -> bool:
    """AAAA-MM-JJ (forme seule)."""
    b = d.encode("utf-8")
    return len(b) == 10 and b[4:5] == b"-" and b[7:8] == b"-" and all(
        i in (4, 7) or c in "0123456789" for i, c in enumerate(d))


# ─────────────────────────── Calcul ───────────────────────────

def calculer(scenario: dict | Scenario, instantane: Instantane) -> dict[str, Any]:
    """Calcule le scénario sur l'instantané ; rend le résultat `calcul.autonomie.v1` en dict JSON.

    Un scénario hors des bornes (date mal formée, GIR hors de 1 à 6, montant négatif, taux au-delà de
    90 %) rend un résultat `erreur` avec son `message` ; un scénario illisible lève `ScenarioInvalide`."""
    s = scenario if isinstance(scenario, Scenario) else lire_scenario(scenario)
    with localcontext(_dec.CONTEXTE):
        return _calculer(s, instantane)


def _calculer(s: Scenario, instantane: Instantane) -> dict[str, Any]:
    if not date_valide(s.date):
        return _erreur(s.date, f"date invalide : {s.date} (AAAA-MM-JJ)")
    p = s.personne
    if p.gir is not None and not 1 <= p.gir <= 6:
        return _erreur(s.date, "GIR : de 1 à 6")
    plan = s.plan
    aide = plan.aide_humaine if plan else None
    negatifs = [
        aide.heures if aide else None, aide.tarif if aide else None, plan.taux_participation if plan else None,
        s.ressources.mensuelles if s.ressources else None,
        s.realise.heures_dans_plan if s.realise else None, s.realise.heures_hors_plan if s.realise else None,
        s.realise.prix_horaire if s.realise else None, s.fiscal.plafond_disponible if s.fiscal else None,
    ]
    if any(d is not None and d < ZERO for d in negatifs):
        return _erreur(s.date, "les heures, tarifs, taux et montants sont positifs ou nuls")
    if plan and plan.taux_participation is not None and plan.taux_participation > Decimal(90):
        return _erreur(s.date, "taux de participation : 90 % au plus (CASF R. 232-11)")

    lecteur = Lecteur(instantane)
    r = _resultat(s.date, s.periode)
    controles: list[dict] = r["controles"]
    plafonds: list[_Ligne] = []
    participations: list[_Ligne] = []
    mois: list[_Ligne] = []
    fin: dict[str, str | None] = r["financement"]
    indisponibles: list[dict] = r["indisponibles"]
    signalements: list[str] = r["signalements"]
    date = s.date
    debut_annee = f"{date[:4]}-01-01"

    def indisponible(id: str, motif: str) -> None:
        indisponibles.append({"id": id, "motif": motif})

    # Contrôles d'orientation : jamais une décision, un état des conditions connues.
    apa_exclue: str | None = None
    if p.age is None:
        controles.append(_controle("age", "60 ans ou plus", "inconnu"))
    elif p.age >= 60:
        controles.append(_controle("age", "60 ans ou plus", "ok"))
    else:
        apa_exclue = "moins de 60 ans : pas d'APA ; la PCH est la piste à examiner avec la MDPH"
        controles.append(_controle("age", "60 ans ou plus", "non", "La PCH relève de la MDPH et de la CDAPH."))
    if p.gir is None:
        controles.append(_controle("gir", "GIR 1 à 4", "inconnu",
                                   "Le GIR est fixé par l'équipe médico-sociale du département ; il n'est jamais déduit ici."))
    elif p.gir <= 4:
        controles.append(_controle("gir", "GIR 1 à 4", "ok", f"GIR {p.gir} communiqué ; origine et date à vérifier."))
    else:
        if apa_exclue is None:
            apa_exclue = (f"GIR {p.gir} : pas d'APA ; caisse de retraite ou service autonomie du département ; "
                          "une évolution récente peut justifier une nouvelle évaluation")
        controles.append(_controle("gir", "GIR 1 à 4", "non",
                                   "Caisse de retraite, service autonomie du département ; réévaluation si l'état a changé."))
    if p.domicile is None:
        controles.append(_controle("domicile", "Vie à domicile", "inconnu"))
    elif p.domicile:
        controles.append(_controle("domicile", "Vie à domicile", "ok"))
    else:
        if apa_exclue is None:
            apa_exclue = "APA en établissement : hors de ce démonstrateur"
        controles.append(_controle("domicile", "Vie à domicile", "non", "L'APA en établissement a ses propres règles."))
    if p.pch_accordee is True:
        controles.append(_controle(
            "pch", "APA et PCH ne se cumulent pas", "a_verifier",
            "Droit d'option (CASF L. 245-9) si les conditions de l'APA sont réunies ; le choix appartient à la personne."))
        signalements.append(f"PCH accordée : APA et PCH ne se cumulent pas ; droit d'option à examiner avec la MDPH et le département ({L245_9}).")

    # Plafond du GIR, à part du plan personnel.
    if p.gir is not None and p.gir <= 4:
        g = p.gir
        plafond = lecteur.valeur("apa.domicile.plafond", [("gir", str(g))], date)
        if plafond is not None:
            lp = _Ligne("plafond", f"Plafond mensuel du plan d'aide, GIR {g}", plafond)
            lp.source = _parametre("apa.domicile.plafond")
            # Borne du plan : jamais convertie en heures auxquelles la personne aurait droit.
            lp.hypothese = "Borne du plan, pas un montant attribué ni un nombre d'heures dû ; de nombreux plans restent en deçà."
            plafonds.append(lp)
        else:
            signalements.append(f"Plafond du GIR {g} indisponible pour le {date}.")

    # Plan accepté.
    h_prevues = aide.heures if aide else None
    tarif = aide.tarif if aide else None
    autres = somme([x.montant for x in plan.autres_postes if x.montant is not None]) if plan else ZERO
    plan_aide = _dec.centime(fois(h_prevues, tarif)) if h_prevues is not None and tarif is not None else None
    plan_accepte = plus(plan_aide, autres) if plan_aide is not None else None
    if plan_accepte is not None and plan is not None:
        fin["plan_accepte"] = _dec.montant(plan_accepte)
        if plan.statut is not None and plan.statut != "notifie":
            signalements.append("Plan non notifié : montants indicatifs, à confirmer par la notification du département.")
        plafond_lu = _dec.parse(plafonds[0].montant) if plafonds else None
        if plafond_lu is not None and plan_accepte > plafond_lu:
            signalements.append(
                f"Plan accepté ({euros(plan_accepte)}) au-dessus du plafond du GIR ({euros(plafond_lu)}) : majoration "
                "pour le proche aidant (répit, hospitalisation) ou transcription à vérifier.")

    # Tarif de prise en charge : au moins le tarif socle national des SAD (CASF L. 314-2-1).
    if tarif is not None:
        socle = lecteur.valeur("sad.tarif_minimal", [], date)
        if socle is not None and tarif < socle:
            signalements.append(
                f"Tarif de prise en charge ({euros(tarif)}) inférieur au tarif socle national des services autonomie "
                f"à domicile ({euros(socle)}) : à vérifier sur la notification (CASF L. 314-2-1).")

    # Taux de participation.
    taux_plan: Decimal | None = None
    taux_notifie = False
    if apa_exclue is None:
        if plan is not None and plan.taux_participation is not None:
            taux_plan = pct(plan.taux_participation)
            taux_notifie = True
        elif s.ressources is not None and s.ressources.mensuelles is not None and plan_accepte is not None:
            res = s.ressources
            b = bareme(lecteur, debut_annee)
            if b is not None:
                brut = res.mensuelles
                ressources = divise(brut, Decimal("1.7")) if res.couple else brut
                lr = _Ligne("ressources", "Ressources mensuelles retenues", ressources)
                if res.couple:
                    lr.base = f"{euros(brut)} ÷ 1,7 (couple à domicile)"
                lr.source = _provenance_source(res.provenance)
                if res.provenance == "hypothese":
                    lr.hypothese = "Ressources au sens des art. R. 232-5 et R. 232-6, à confirmer."
                participations.append(lr)
                a1, a2, a3 = fractions(plan_accepte, b)
                for id, lib, v in (("a1", "Fraction A1 du plan accepté", a1), ("a2", "Fraction A2", a2), ("a3", "Fraction A3", a3)):
                    lf = _Ligne(id, lib, v)
                    lf.source = _parametre("apa.domicile.participation.fraction.coefficient")
                    participations.append(lf)
                pp = participation_plan(plan_accepte, ressources, b)
                t = taux(plan_accepte, ressources, b)
                lp = _Ligne("participation_plan", "Participation calculée sur le plan accepté", _dec.centime(pp))
                lp.base = euros(plan_accepte)
                lp.taux = _dec.nombre(arrondi_pair(fois(t, _dec.CENT), 4))
                lp.unite = "%"
                lp.source = _loi("CASF, art. R. 232-11", R232_11)
                bas, haut = fois(b.seuil_bas, b.mtp), fois(b.seuil_haut, b.mtp)
                if ressources <= bas:
                    lp.hypothese = f"Ressources au plus égales à {euros(_dec.centime(bas))} : participation nulle."
                elif ressources > haut:
                    lp.hypothese = f"Ressources au-delà de {euros(_dec.centime(haut))} : participation de 90 %."
                else:
                    lp.hypothese = (f"Ressources entre {euros(_dec.centime(bas))} et {euros(_dec.centime(haut))} : "
                                    "formule de R. 232-11, fractions pondérées.")
                participations.append(lp)
                taux_plan = t
            else:
                signalements.append(f"Barème de participation indisponible au {debut_annee}.")
    if taux_plan is not None:
        fin["taux_participation"] = _dec.nombre(arrondi_pair(fois(taux_plan, _dec.CENT), 4))

    # Mois réalisé.
    realise = s.realise
    prix = realise.prix_horaire if realise else None
    h_dans = realise.heures_dans_plan if realise else None
    h_hors = realise.heures_hors_plan if realise and realise.heures_hors_plan is not None else ZERO
    prov_facture = _provenance_source(realise.provenance if realise else "hypothese")
    prov_plan = _provenance_source(plan.provenance if plan else "hypothese")
    if realise is not None and realise.facture_nette_apa:
        signalements.append("Facture déjà nette de l'APA versée au service : ne pas la déduire une seconde fois ; "
                            "le reste se lit directement sur la facture.")

    # Heures : couvertes dans la limite de la ligne du plan, l'excédent est hors plan.
    if h_dans is None:
        couvertes, excedent = None, ZERO
    elif h_prevues is None:
        couvertes, excedent = None, h_dans
    elif h_dans > h_prevues:
        couvertes, excedent = h_prevues, moins(h_dans, h_prevues)
    else:
        couvertes, excedent = h_dans, ZERO
    report = date >= REPORT_DEPUIS
    if excedent > ZERO and h_prevues is not None:
        if report:
            signalements.append(
                f"{h(excedent)} réalisées au-delà de la ligne du plan : comptées hors plan dans ce calcul. Il peut "
                "s'agir d'heures non utilisées des cinq mois précédents, reportables même au-delà du plafond mensuel, "
                f"au tarif et à la participation du mois d'utilisation (CASF, art. D. 232-17-1 : {D232_17_1}) ; le démonstrateur n'a pas cet "
                "historique : à vérifier avec le service et le département.")
        else:
            signalements.append(f"{h(excedent)} réalisées au-delà de la ligne du plan : comptées hors plan, à vérifier avec le service.")
    hors = plus(h_hors, excedent)
    besoin = s.besoin.heures_estimees if s.besoin else None
    heures = r["heures"]
    heures["besoin_estime"] = _dec.nombre(besoin) if besoin is not None else None
    heures["prevues"] = _dec.nombre(h_prevues) if h_prevues is not None else None
    heures["realisees_dans_plan"] = _dec.nombre(couvertes) if couvertes is not None else None
    heures["non_realisees"] = (_dec.nombre(max(moins(h_prevues, couvertes), ZERO))
                               if h_prevues is not None and couvertes is not None else None)
    heures["hors_plan"] = _dec.nombre(hors) if realise is not None else None
    if besoin is not None and h_prevues is not None and besoin > h_prevues:
        signalements.append(f"Besoin estimé ({h(besoin)}) au-delà du plan ({h(h_prevues)}) : à discuter lors d'une "
                            "réévaluation, pas un coût supplémentaire.")
    nr = _dec.parse(heures["non_realisees"]) if heures["non_realisees"] is not None else None
    if nr is not None and nr > ZERO:
        if report:
            signalements.append(f"{h(nr)} prévues non réalisées ce mois : motif à préciser avec le service ; elles "
                                f"restent utilisables au cours des cinq mois suivants, après les heures de chaque mois (CASF, art. D. 232-17-1 : {D232_17_1}).")
        else:
            signalements.append(f"{h(nr)} prévues non réalisées ce mois : motif à préciser avec le service.")

    # Facture brute.
    facture = _dec.centime(fois(plus(h_dans, h_hors), prix)) if prix is not None and h_dans is not None else None
    if facture is not None:
        lf = _Ligne("facture_brute", "Facture brute du service", facture)
        lf.base = f"{h(plus(h_dans, h_hors))} × {euros(prix)}"
        lf.source = dict(prov_facture)
        mois.append(lf)
        fin["facture_brute"] = _dec.montant(facture)

    # Base utilisée, participation, APA.
    apa: Decimal | None = None
    participation: Decimal | None = None
    forfait = plan is not None and plan.forfait
    if apa_exclue is not None:
        indisponible("apa_estimee", apa_exclue)
    elif couvertes is not None and tarif is not None:
        if prix is not None and prix < tarif:
            signalements.append("Tarif facturé par le service inférieur au tarif de prise en charge : base au tarif "
                                "facturé, à vérifier sur la notification et la facture.")
            valo = prix
        else:
            valo = tarif
        base = _dec.centime(fois(couvertes, valo))
        lb = _Ligne("base_utilisee", "Base prise en charge (heures couvertes × tarif de prise en charge)", base)
        lb.base = f"{h(couvertes)} × {euros(valo)}"
        lb.source = dict(prov_plan)
        mois.append(lb)
        fin["base_utilisee"] = _dec.montant(base)
        if taux_plan is not None:
            t = taux_plan
            assiette = (plan_aide if plan_aide is not None else base) if forfait else base
            if forfait:
                signalements.append("Régime forfaitaire : participation et APA calculées sur le plan accepté (CASF "
                                    "L. 232-4, R. 232-11) ; un mois isolé ne se lit pas comme une facture.")
            part = _dec.centime(fois(assiette, t))
            lp = _Ligne("participation", "Participation du bénéficiaire", part)
            lp.base = euros(assiette)
            lp.taux = _dec.nombre(arrondi_pair(fois(t, _dec.CENT), 4))
            lp.unite = "%"
            if taux_notifie:
                lp.source = dict(prov_plan)
                lp.hypothese = "Taux repris de la notification."
            else:
                lp.source = _loi("CASF, art. R. 232-11", R232_11)
                lp.hypothese = "Taux calculé sur le plan accepté (P / A), non arrondi ; la notification peut l'arrondir."
            mois.append(lp)
            montant_apa = moins(assiette, part)
            la = _Ligne("apa_estimee", "APA estimée", montant_apa)
            la.source = _loi("CASF, art. L. 232-4", L232_4)
            seuil = lecteur.valeur("apa.non_versement.seuil", [], date)
            if seuil is not None and ZERO < montant_apa <= seuil:
                la.hypothese = f"Au plus égale à {euros(seuil)} : l'APA n'est pas versée (CASF D. 232-31)."
                la.source = _loi("CASF, art. D. 232-31", D232_31)
                montant_apa = ZERO
                la.montant = _dec.montant(montant_apa)
            mois.append(la)
            participation = part
            apa = montant_apa
            fin["participation"] = _dec.montant(part)
            fin["apa_estimee"] = _dec.montant(montant_apa)
        else:
            for id in ("participation", "apa_estimee"):
                indisponible(id, "taux de participation inconnu (notification) et ressources non renseignées")
    else:
        for id in ("base_utilisee", "participation", "apa_estimee"):
            indisponible(id, "pas de plan d'aide transcrit (heures et tarif de prise en charge)" if tarif is None
                         else "heures réalisées dans le plan inconnues")

    # Dépassement et hors plan.
    depassement: Decimal | None = None
    if couvertes is not None and tarif is not None and prix is not None:
        d = _dec.centime(fois(couvertes, max(moins(prix, tarif), ZERO)))
        ld = _Ligne("depassement", "Part du tarif du service non prise en charge (heures couvertes)", d)
        ld.base = f"{h(couvertes)} × ({euros(prix)} − {euros(tarif)})"
        ld.source = dict(prov_facture)
        mois.append(ld)
        depassement = d
        fin["depassement"] = _dec.montant(d)
    hors_plan: Decimal | None = None
    if prix is not None and realise is not None:
        m = _dec.centime(fois(hors, prix))
        if hors > ZERO:
            lh = _Ligne("hors_plan", "Heures hors plan" if plan_aide is not None else "Heures sans plan d'aide", m)
            lh.base = f"{h(hors)} × {euros(prix)}"
            lh.source = dict(prov_facture)
            mois.append(lh)
        fin["hors_plan"] = _dec.montant(m)
        hors_plan = m

    # Reste avant fiscalité : participation + dépassement + hors plan ; contrôle par la facture.
    reste: Decimal | None = None
    if facture is not None and apa is not None:
        reste = moins(facture, apa)
    elif facture is not None and apa is None and apa_exclue is not None:
        reste = facture
    if (reste is not None and participation is not None and depassement is not None and hors_plan is not None
            and apa is not None):
        total = plus(plus(participation, depassement), hors_plan)
        if apa > ZERO and not forfait and total != reste:
            signalements.append(f"Contrôle : participation + dépassement + hors plan ({euros(total)}) ≠ facture − APA "
                                f"({euros(reste)}) ; vérifier les heures et les tarifs.")
    if reste is not None:
        lr = _Ligne("reste_avant_fiscalite", "Reste à payer avant fiscalité", reste)
        if facture is not None:
            lr.base = f"{euros(facture)} − {euros(apa if apa is not None else ZERO)}"
        mois.append(lr)
        fin["reste_avant_fiscalite"] = _dec.montant(reste)
    else:
        indisponible("reste_avant_fiscalite", "facture inconnue (heures réalisées et tarif du service)" if facture is None
                     else "APA du mois non établie")

    # Crédit d'impôt : seulement si payeur, éligibilité et plafond disponible sont connus.
    fiscal = s.fiscal
    eligible = fiscal.eligible if fiscal else None
    dispo = fiscal.plafond_disponible if fiscal else None
    if reste is not None and eligible is True and dispo is not None:
        tci = lecteur.valeur("credit_impot.emploi_domicile.taux", [], date)
        if tci is not None:
            retenue = min(reste, dispo)
            credit = _dec.centime(fois(retenue, pct(tci)))
            lc = _Ligne("credit_impot_potentiel", "Crédit d'impôt potentiel", credit)
            lc.base = euros(retenue)
            lc.taux = _dec.nombre(tci)
            lc.unite = "%"
            lc.source = _parametre("credit_impot.emploi_domicile.taux")
            lc.hypothese = ("Dépenses payées par le contribuable, éligibles, aides déduites, dans la limite du plafond "
                            "annuel disponible (CGI art. 199 sexdecies) ; perçu l'année suivante.")
            mois.append(lc)
            net = moins(reste, credit)
            ln = _Ligne("cout_net_fiscal_potentiel", "Coût net potentiel après crédit d'impôt", net)
            ln.hypothese = "Le reste avant fiscalité est ce qui est payé dans le mois."
            mois.append(ln)
            fin["credit_impot_potentiel"] = _dec.montant(credit)
            fin["cout_net_fiscal_potentiel"] = _dec.montant(net)
        else:
            signalements.append("Taux du crédit d'impôt indisponible.")
    elif reste is not None and eligible is False:
        for id in ("credit_impot_potentiel", "cout_net_fiscal_potentiel"):
            indisponible(id, "dépenses non éligibles ou non payées par le contribuable")
    else:
        for id in ("credit_impot_potentiel", "cout_net_fiscal_potentiel"):
            indisponible(id, "payeur, éligibilité des lignes ou plafond annuel disponible inconnus")

    # Informations manquantes, dans l'ordre où elles débloquent le calcul.
    manques: list[dict] = r["informations_manquantes"]

    def manque(id: str, question: str, debloque: list[str]) -> None:
        manques.append({"id": id, "question": question, "debloque": debloque})

    if apa_exclue is None:
        sans_plan = (plan is None or plan.statut == "envisage") and aide is None
        if sans_plan:
            manque("plan", "Une demande d'APA a-t-elle été déposée auprès du département ? Le plan notifié après "
                   "l'évaluation à domicile donnera les heures et le tarif retenus.",
                   ["base_utilisee", "participation", "apa_estimee", "depassement", "reste_avant_fiscalite"])
        elif tarif is None or h_prevues is None:
            manque("plan", "Quelles heures mensuelles d'aide humaine et quel tarif horaire de prise en charge la "
                   "notification prévoit-elle ?",
                   ["base_utilisee", "participation", "apa_estimee", "depassement", "reste_avant_fiscalite"])
        if taux_plan is None and not sans_plan:
            manque("taux_participation", "Quel taux de participation figure sur la notification ? À défaut, quelles "
                   "ressources mensuelles sont retenues ?", ["participation", "apa_estimee", "reste_avant_fiscalite"])
    if h_dans is None:
        manque("heures_realisees", "Combien d'heures le service a-t-il réalisées ce mois-ci dans le plan, et combien hors plan ?",
               ["facture_brute", "base_utilisee", "depassement", "hors_plan", "reste_avant_fiscalite"])
    if prix is None:
        manque("prix_horaire", "Quel tarif horaire le service facture-t-il ?",
               ["facture_brute", "depassement", "hors_plan", "reste_avant_fiscalite"])
    if p.gir is None:
        manque("gir", "Quel GIR l'équipe médico-sociale a-t-elle retenu, et à quelle date ?", ["plafond"])
    if reste is not None and not (eligible is not None and dispo is not None):
        manque("fiscal", "Les dépenses sont-elles payées par la personne et éligibles au crédit d'impôt, et quelle "
               "part du plafond annuel reste disponible ?", ["credit_impot_potentiel", "cout_net_fiscal_potentiel"])

    signalements.extend(AVERTISSEMENTS)
    r["plafond"] = [x.vers_json() for x in plafonds]
    r["participation"] = [x.vers_json() for x in participations]
    r["mois"] = [x.vers_json() for x in mois]
    r["valeurs"] = lecteur.utilisees()
    if not all(i["id"].startswith(("credit_impot", "cout_net")) for i in indisponibles):
        r["statut"] = "partiel"
    return r
