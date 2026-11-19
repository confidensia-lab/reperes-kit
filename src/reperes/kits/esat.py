"""Rémunération garantie d'un travailleur d'ESAT (`calcul.esat.v1`).

Part financée par l'ESAT, aide au poste de l'État, rémunération garantie, bornes réglementaires,
temps partiel, plafond de l'intéressement (CASF L. 243-4, R. 243-5, R. 243-6), puis cotisations du
mois, net du travailleur, compensation par l'État et coût pour l'ESAT. La rémunération garantie n'est
pas un salaire (L. 243-5) : contrat propre, distinct des conventions collectives.

    from reperes.kits import esat
    from reperes.kits.valeurs import Instantane

    inst = Instantane.charger("esat-2026-11.json")
    r = esat.calculer({"date": "2026-07-15", "part_esat": {"pct_smic": "20"}}, inst)
    r["remuneration_garantie"]["mensuel"]
"""
from __future__ import annotations

import datetime as _dt

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable

from . import _dec
from .valeurs import Instantane, Lecteur

SCHEMA = "calcul.esat.v1"

# Paramètres propres à la rémunération garantie.
PARAMETRES_ESAT = (
    "esat.remuneration_garantie.coefficient", "esat.aide_au_poste.coefficient", "esat.part_esat.minimum",
    "esat.aide_au_poste.seuil", "esat.aide_au_poste.reduction", "esat.interessement.plafond",
    "esat.prevoyance.compensation", "esat.complementaire_sante.compensation", "esat.formation.taux",
    "esat.formation.assiette_aide",
)

# Identifiants d'Étalon lus par le calcul : SMIC, cotisations communes et paramètres propres.
PARAMETRES = (
    "smic.mensuel", "pss.mensuel", "cotisation.vieillesse_plafonnee", "cotisation.vieillesse_deplafonnee",
    "agirc_arrco.taux_appele_part", "agirc_arrco.ceg", "agirc_arrco.repartition", "csg.abattement", "csg.taux",
    "crds.taux", "cotisation.maladie", "cotisation.allocations_familiales", "cotisation.csa",
    "atmp.taux_collectif", "cotisation.fnal",
) + PARAMETRES_ESAT

# Code risque AT/MP des travailleurs handicapés des ESAT (arrêté annuel de tarification).
CODE_RISQUE = "85.3HA"
# Première date du calcul des cotisations (comme le net et le coût des conventions collectives).
COTISATIONS_DEPUIS = "2026-01-01"

UN = Decimal(1)
ZERO = Decimal(0)


# ── Demande ──────────────────────────────────────────────────────────────────────────────────

class DemandeInvalide(ValueError):
    """Demande illisible (champ manquant ou de mauvais type) : refusée avant tout calcul."""


def _decimal(v: Any, champ: str) -> Decimal:
    """Décimal d'un champ de la demande : texte (« 0.8 », « 1e2 ») ou nombre JSON."""
    if isinstance(v, bool):
        raise DemandeInvalide(f"{champ} : nombre attendu")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return _decimal(repr(v), champ)
    if isinstance(v, str):
        try:
            d = Decimal(v)
        except InvalidOperation:
            d = None
        if d is not None and d.is_finite() and v == v.strip() and "_" not in v:
            return d
    raise DemandeInvalide(f"{champ} : nombre attendu")


def _decimal_option(objet: dict[str, Any], cle: str, champ: str) -> Decimal | None:
    v = objet.get(cle)
    return None if v is None else _decimal(v, champ)


def _objet(v: Any, champ: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise DemandeInvalide(f"{champ} : objet attendu")
    return v


def lire_demande(demande: dict[str, Any]) -> dict[str, Any]:
    """Demande normalisée : `date`, `temps_travail` (1 par défaut), `pct_smic` et `mensuelle` (part de
    l'ESAT), `effectif` (absent : 50 et plus), `sante_esat`, `sante_travailleur`, `prevoyance_esat`.

    Lève `DemandeInvalide` si un champ requis manque ou n'a pas le bon type."""
    d = _objet(demande, "demande")
    # Date absente : aujourd'hui, comme l'API.
    date = d.get("date", _dt.date.today().isoformat())
    if not isinstance(date, str):
        raise DemandeInvalide("date : texte AAAA-MM-JJ attendu")
    tt = d.get("temps_travail")
    if "part_esat" not in d:
        raise DemandeInvalide("part_esat : champ requis")
    part = _objet(d["part_esat"], "part_esat")
    effectif = d.get("effectif")
    if effectif is not None and (isinstance(effectif, bool) or not isinstance(effectif, int) or not 0 <= effectif <= 0xFFFFFFFF):
        raise DemandeInvalide("effectif : entier positif attendu")
    couverture = d.get("couverture")
    couverture = {} if couverture is None else _objet(couverture, "couverture")
    return {
        "date": date,
        "temps_travail": UN if tt is None else _decimal(tt, "temps_travail"),
        "pct_smic": _decimal_option(part, "pct_smic", "part_esat.pct_smic"),
        "mensuelle": _decimal_option(part, "mensuelle", "part_esat.mensuelle"),
        "effectif": effectif,
        "sante_esat": _decimal_option(couverture, "sante_esat", "couverture.sante_esat"),
        "sante_travailleur": _decimal_option(couverture, "sante_travailleur", "couverture.sante_travailleur"),
        "prevoyance_esat": _decimal_option(couverture, "prevoyance_esat", "couverture.prevoyance_esat"),
    }


# ── Mise en forme ────────────────────────────────────────────────────────────────────────────

def _pct(d: Decimal) -> str:
    """Pourcentage du SMIC, deux décimales."""
    return f"{_dec.centime(d):.2f}"


def _sans_vides(o: dict[str, Any]) -> dict[str, Any]:
    """Champs `None` omis, comme `skip_serializing_if = "Option::is_none"`."""
    return {k: v for k, v in o.items() if v is not None}


def _ligne(id: str, libelle: str, montant: Decimal, base: str | None, taux: Decimal | None,
           parametre: str | None, hypothese: str | None) -> dict[str, Any]:
    return _sans_vides({
        "id": id, "libelle": libelle, "base": base,
        "taux": None if taux is None else _dec.nombre(_dec.centime(taux)),
        "unite": None if taux is None else "%", "montant": _dec.montant(montant),
        "source": None if parametre is None else {"parametre": parametre}, "hypothese": hypothese,
    })


def _ligne_taux(id: str, libelle: str, base: Decimal, taux: Decimal, montant: Decimal, parametre: str,
                hypothese: str | None = None) -> dict[str, Any]:
    return _sans_vides({
        "id": id, "libelle": libelle, "base": _dec.montant(base), "taux": _dec.nombre(taux), "unite": "%",
        "montant": _dec.montant(montant), "source": {"parametre": parametre}, "hypothese": hypothese,
    })


def _ligne_montant(id: str, libelle: str, montant: Decimal, hypothese: str) -> dict[str, Any]:
    return {"id": id, "libelle": libelle, "montant": _dec.montant(montant), "hypothese": hypothese}


def _erreur(d: dict[str, Any], message: str, valeurs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA, "statut": "erreur", "message": message, "date": d["date"],
        "temps_travail": _dec.nombre(d["temps_travail"]), "lignes": [], "controles": [], "signalements": [],
        "valeurs": valeurs,
    }


# ── Calcul ───────────────────────────────────────────────────────────────────────────────────

def calculer(demande: dict[str, Any], instantane: Instantane) -> dict[str, Any]:
    """Résultat `calcul.esat.v1` (dict JSON) de la demande sur l'instantané.

    Erreur de date, de temps de travail, de part de l'ESAT ou valeur d'Étalon absente : résultat de
    statut `erreur` avec `message`. Demande illisible : `DemandeInvalide`."""
    d = lire_demande(demande)
    with localcontext(_dec.CONTEXTE):
        return _calculer(d, instantane)


def _calculer(d: dict[str, Any], instantane: Instantane) -> dict[str, Any]:
    date: str = d["date"]
    b = date.encode("utf-8")
    if len(b) != 10 or b[4:5] != b"-" or b[7:8] != b"-":
        return _erreur(d, f"date invalide : {date} (AAAA-MM-JJ)", [])
    t: Decimal = d["temps_travail"]
    if t <= ZERO or t > UN:
        return _erreur(d, "temps de travail : part d'un temps plein entre 0 et 1", [])
    lecteur = Lecteur(instantane)

    def lire(id: str, c: list[tuple[str, str]] | None = None) -> Decimal | None:
        return lecteur.valeur(id, c or [], date)

    lues = (
        lire("smic.mensuel"),
        lire("esat.remuneration_garantie.coefficient", [("borne", "minimum")]),
        lire("esat.remuneration_garantie.coefficient", [("borne", "maximum")]),
        lire("esat.aide_au_poste.coefficient"),
        lire("esat.part_esat.minimum"),
        lire("esat.aide_au_poste.seuil"),
        lire("esat.aide_au_poste.reduction"),
        lire("esat.interessement.plafond"),
    )
    if any(x is None for x in lues):
        return _erreur(d, f"valeurs d'Étalon absentes au {date} (SMIC ou coefficients de la rémunération garantie)",
                       lecteur.utilisees())
    smic, rg_min, rg_max, aide_max, part_min, seuil, reduction, inter = lues
    smic_t = smic * t
    cent = _dec.CENT
    if d["pct_smic"] is not None and d["mensuelle"] is None:
        p = d["pct_smic"]
    elif d["pct_smic"] is None and d["mensuelle"] is not None:
        p = d["mensuelle"] / smic_t * cent
    else:
        return _erreur(d, "part de l'ESAT : `pct_smic` ou `mensuelle`, l'un des deux", lecteur.utilisees())
    if p < ZERO or p > Decimal(200):
        return _erreur(d, "part de l'ESAT hors de toute plage plausible (0 à 200 % du SMIC)", lecteur.utilisees())
    # Aide au poste : maximale jusqu'au seuil, puis réduite de `reduction` point par point de part ESAT
    # au-delà (lecture continue), jamais négative.
    degressif = p > seuil
    aide = max(aide_max - reduction * (p - seuil), ZERO) if degressif else aide_max
    rg = p + aide

    def montant(x: Decimal) -> Decimal:
        return x / cent * smic_t

    m_part, m_aide = _dec.centime(montant(p)), _dec.centime(montant(aide))
    m_rg = m_part + m_aide

    base_smic = _dec.montant(smic_t)
    fr = _dec.fr
    smic_txt = "SMIC mensuel" if t == UN else f"SMIC mensuel × {fr(t * cent, 0)} % d'un temps plein"
    if degressif:
        hyp_aide = (f"{fr(aide_max, 1)} % du SMIC, moins {fr(reduction, 1)} point par point de part de l'ESAT "
                    f"au-delà de {fr(seuil, 0)} % ({fr(p - seuil, 2)} points), réduction appliquée de façon continue")
    else:
        hyp_aide = f"{fr(aide_max, 1)} % du SMIC tant que la part de l'ESAT ne dépasse pas {fr(seuil, 0)} %"
    lignes = [
        _ligne("part_esat", "Part financée par l'ESAT", m_part, base_smic, p, "smic.mensuel",
               f"{smic_txt} ; saisie en euros, convertie en part du SMIC" if d["mensuelle"] is not None else smic_txt),
        _ligne("aide_au_poste", "Aide au poste (État)", m_aide, base_smic, aide, "esat.aide_au_poste.coefficient", hyp_aide),
        _ligne("remuneration_garantie", "Rémunération garantie", m_rg, "part de l'ESAT + aide au poste", None, None,
               f"{fr(rg, 2)} % du SMIC"),
    ]

    def ok(v: bool) -> str:
        return "ok" if v else "non"

    controles = [_sans_vides({
        "id": "part_minimale", "libelle": f"Part de l'ESAT d'au moins {fr(part_min, 0)} % du SMIC", "statut": ok(p >= part_min),
        "detail": f"{fr(p, 2)} % : l'ESAT doit financer au moins {fr(part_min, 0)} % du SMIC (CASF R. 243-6)" if p < part_min else None,
    })]
    if rg > rg_max:
        detail = (f"{fr(rg, 2)} % : au-dessus du plafond de {fr(rg_max, 1)} % (CASF R. 243-5) ; la part de l'ESAT ne peut "
                  f"dépasser {fr(seuil + (rg_max - aide_max - seuil) / (UN - reduction), 1)} % du SMIC")
    elif rg < rg_min:
        detail = f"{fr(rg, 2)} % : sous le plancher de {fr(rg_min, 1)} % (CASF R. 243-5)"
    else:
        detail = None
    controles.append(_sans_vides({
        "id": "bornes", "libelle": f"Rémunération garantie entre {fr(rg_min, 1)} % et {fr(rg_max, 1)} % du SMIC",
        "statut": ok(rg_min <= rg <= rg_max), "detail": detail,
    }))
    signalements: list[str] = []
    if t < UN:
        signalements.append("Temps partiel : rémunération garantie et aide au poste réduites en proportion (CASF R. 243-5, L. 243-4).")
    plafond_inter = _dec.centime(m_part * Decimal(12) * inter / cent)
    signalements.append(
        f"Intéressement : prime plafonnée à {fr(inter, 0)} % de la part annuelle financée par l'ESAT, soit "
        f"{fr(plafond_inter, 2)} € si cette part reste la même sur l'exercice (CASF R. 243-6).")
    if date >= COTISATIONS_DEPUIS:
        cotisations = cotiser(d, lecteur, m_rg, m_part, m_aide, signalements)
    else:
        signalements.append("Cotisations, net du travailleur et compensation par l'État calculés à partir du "
                            "1er janvier 2026 : rémunération garantie seule à cette date.")
        cotisations = None
    statut = "ok" if all(c["statut"] == "ok" for c in controles) else "partiel"
    if cotisations is None and date >= COTISATIONS_DEPUIS:
        statut = "partiel"
    return _sans_vides({
        "schema_version": SCHEMA, "statut": statut, "date": date, "temps_travail": _dec.nombre(t),
        "smic_mensuel": _dec.montant(smic),
        "part_esat": {"pct_smic": _pct(p), "mensuel": _dec.montant(m_part)},
        "aide_au_poste": {"pct_smic": _pct(aide), "mensuel": _dec.montant(m_aide)},
        "remuneration_garantie": {"pct_smic": _pct(rg), "mensuel": _dec.montant(m_rg)},
        "bornes": {"minimum": _dec.montant(montant(rg_min)), "maximum": _dec.montant(montant(rg_max))},
        "interessement_plafond_annuel": _dec.montant(plafond_inter),
        "lignes": lignes, "cotisations": cotisations, "controles": controles, "signalements": signalements,
        "valeurs": lecteur.utilisees(),
    })


def _somme(lignes: list[dict[str, Any]]) -> Decimal:
    return sum((_dec.parse(x["montant"]) or ZERO for x in lignes), ZERO)


def cotiser(d: dict[str, Any], lecteur: Lecteur, rg: Decimal, part: Decimal, aide: Decimal,
            signalements: list[str]) -> dict[str, Any] | None:
    """Cotisations sur la rémunération garantie (CASF L. 243-5, R. 243-9).

    Pas d'assurance chômage, donc hors du champ de la réduction générale (CSS L. 241-13, II) ; AT/MP du
    code risque 85.3HA ; retraite complémentaire à la répartition légale, sans part salariale de la CEG
    (commissions paritaires Agirc-Arrco) ; compensation par l'État de la part employeur des cotisations
    de R. 243-9 afférente à l'aide au poste (L. 243-6, arrêté du 28 décembre 2006), de la prévoyance
    (2 % de la part de l'ESAT, arrêté du 14 mai 2007) et de la moitié de la complémentaire santé (arrêté
    du 25 août 2025). `None` si une valeur d'Étalon manque (signalée). `d` : demande normalisée
    (`lire_demande`) ; montants du mois arrondis au centime ; sous `localcontext(_dec.CONTEXTE)`."""
    date: str = d["date"]
    manque: list[str] = []

    def v(id: str, c: list[tuple[str, str]] | None = None) -> Decimal:
        x = lecteur.valeur(id, c or [], date)
        if x is None:
            manque.append(id)
        return ZERO if x is None else x

    pmss = v("pss.mensuel")
    vp_s, vd_s = v("cotisation.vieillesse_plafonnee", [("part", "salarie")]), v("cotisation.vieillesse_deplafonnee", [("part", "salarie")])
    vp_e, vd_e = v("cotisation.vieillesse_plafonnee", [("part", "employeur")]), v("cotisation.vieillesse_deplafonnee", [("part", "employeur")])
    aa_s = v("agirc_arrco.taux_appele_part", [("tranche", "t1"), ("part", "salarie")])
    aa_e = v("agirc_arrco.taux_appele_part", [("tranche", "t1"), ("part", "employeur")])
    ceg, rep_e = v("agirc_arrco.ceg", [("tranche", "t1")]), v("agirc_arrco.repartition", [("part", "employeur")])
    abatt, csg, csg_ded, crds = v("csg.abattement"), v("csg.taux", [("nature", "global")]), v("csg.taux", [("nature", "deductible")]), v("crds.taux")
    maladie, af, csa, atmp = v("cotisation.maladie"), v("cotisation.allocations_familiales"), v("cotisation.csa"), v("atmp.taux_collectif", [("code_risque", CODE_RISQUE)])
    n = 50 if d["effectif"] is None else d["effectif"]
    fnal = v("cotisation.fnal", [("effectif", "50_et_plus" if n >= 50 else "moins_de_50")])
    comp_prev, comp_sante = v("esat.prevoyance.compensation"), v("esat.complementaire_sante.compensation")
    formation, assiette_aide = v("esat.formation.taux"), v("esat.formation.assiette_aide")
    if manque:
        signalements.append(f"Cotisations non calculées : valeurs d'Étalon absentes au {date} ({', '.join(manque)}).")
        return None
    pc: Callable[[Decimal], Decimal] = _dec.pct
    c: Callable[[Decimal], Decimal] = _dec.centime

    def retenue(x: Decimal) -> Decimal:
        """Retenue du travailleur : opposé du montant arrondi, signe conservé sur zéro comme le moteur."""
        return c(x).copy_negate()

    t1 = min(rg, pmss)
    sante_esat, sante_travailleur, prevoyance_esat = d["sante_esat"], d["sante_travailleur"], d["prevoyance_esat"]

    # ── Travailleur ──
    sal = [
        _ligne_taux("vieillesse_plafonnee", "Assurance vieillesse plafonnée", t1, vp_s, retenue(t1 * pc(vp_s)), "cotisation.vieillesse_plafonnee"),
        _ligne_taux("vieillesse_deplafonnee", "Assurance vieillesse déplafonnée", rg, vd_s, retenue(rg * pc(vd_s)), "cotisation.vieillesse_deplafonnee"),
        _ligne_taux("agirc_arrco_t1", "Retraite complémentaire Agirc-Arrco, tranche 1", t1, aa_s, retenue(t1 * pc(aa_s)), "agirc_arrco.taux_appele_part"),
    ]
    contributions = (sante_esat or ZERO) + (prevoyance_esat or ZERO)
    abattue = rg * (UN - pc(abatt)) + contributions
    sal.append(_ligne_taux("csg_deductible", "CSG déductible", abattue, csg_ded, retenue(abattue * pc(csg_ded)), "csg.taux"))
    sal.append(_ligne_taux("csg_non_deductible", "CSG non déductible", abattue, csg - csg_ded, retenue(abattue * pc(csg - csg_ded)), "csg.taux"))
    sal.append(_ligne_taux("crds", "CRDS", abattue, crds, retenue(abattue * pc(crds)), "crds.taux"))
    if sante_travailleur is not None:
        sal.append(_ligne_montant("sante", "Complémentaire santé, part du travailleur", sante_travailleur.copy_negate(), "montant saisi"))

    # ── ESAT, avant compensation ──
    ceg_e = c(ceg * pc(rep_e))
    # Cotisations de R. 243-9 (sécurité sociale, retraite complémentaire) : compensées sur l'aide au poste.
    compensables = [
        _ligne_taux("maladie", "Assurance maladie (taux plein)", rg, maladie, c(rg * pc(maladie)), "cotisation.maladie"),
        _ligne_taux("vieillesse_plafonnee", "Assurance vieillesse plafonnée", t1, vp_e, c(t1 * pc(vp_e)), "cotisation.vieillesse_plafonnee"),
        _ligne_taux("vieillesse_deplafonnee", "Assurance vieillesse déplafonnée", rg, vd_e, c(rg * pc(vd_e)), "cotisation.vieillesse_deplafonnee"),
        _ligne_taux("allocations_familiales", "Allocations familiales (taux plein)", rg, af, c(rg * pc(af)), "cotisation.allocations_familiales"),
        _ligne_taux("atmp", "Accidents du travail (code risque 85.3HA)", rg, atmp, c(rg * pc(atmp)), "atmp.taux_collectif"),
        _ligne_taux("agirc_arrco_t1", "Retraite complémentaire Agirc-Arrco, tranche 1", t1, aa_e, c(t1 * pc(aa_e)), "agirc_arrco.taux_appele_part"),
        _ligne_taux("ceg_t1", "Contribution d'équilibre général, tranche 1", t1, ceg_e, c(t1 * pc(ceg_e)), "agirc_arrco.ceg"),
    ]
    # FNAL et CSA : sur la part de l'ESAT seulement, l'aide au poste en est exclue (lettre-circulaire Acoss
    # n° 2008-090). Moins de 50 salariés : FNAL sur la part plafonnée, la part de l'ESAT ne dépasse pas le PMSS.
    exclue = "aide au poste exclue de l'assiette (lettre-circulaire Acoss n° 2008-090)"
    base_fnal = part if n >= 50 else min(part, pmss)
    # Contribution au compte personnel de formation : part de l'ESAT plus une fraction de l'aide au poste.
    aide_formation = c(aide * pc(assiette_aide))
    base_formation = part + aide_formation
    autres = [
        _ligne_taux("csa", "Contribution solidarité autonomie", part, csa, c(part * pc(csa)), "cotisation.csa", exclue),
        _ligne_taux("fnal", "FNAL", base_fnal, fnal, c(base_fnal * pc(fnal)), "cotisation.fnal", exclue),
        _ligne_taux("formation_cpf", "Contribution au compte personnel de formation", base_formation, formation,
                    c(base_formation * pc(formation)), "esat.formation.taux",
                    "part de l'ESAT plus la moitié de l'aide au poste (C. trav. D. 6323-29-2)"),
    ]
    if sante_esat is not None:
        autres.append(_ligne_montant("sante", "Complémentaire santé, part de l'ESAT", sante_esat, "montant saisi"))
    if prevoyance_esat is not None:
        autres.append(_ligne_montant("prevoyance", "Prévoyance, cotisation de l'ESAT", prevoyance_esat, "montant saisi"))
    base_comp = _somme(compensables)

    # ── Compensation par l'État ──
    comp = []
    if rg > ZERO:
        comp.append({
            "id": "compensation_cotisations", "libelle": "Cotisations afférentes à l'aide au poste",
            "base": _dec.montant(base_comp), "taux": _dec.nombre(c(aide / rg * _dec.CENT)), "unite": "%",
            "montant": _dec.montant(c(base_comp * aide / rg)),
            "hypothese": "part employeur des cotisations de R. 243-9 au prorata de l'aide au poste (CASF L. 243-6 ; arrêté du 28 décembre 2006)",
        })
    comp.append(_ligne_taux("compensation_formation", "Contribution au compte personnel de formation", aide_formation, formation,
                            c(aide_formation * pc(formation)), "esat.formation.taux",
                            "contribution afférente à la fraction de l'assiette égale à l'aide au poste (CASF L. 243-6)"))
    if prevoyance_esat is not None:
        comp.append(_ligne_taux("compensation_prevoyance", "Prévoyance", part, comp_prev,
                                c(min(part * pc(comp_prev), prevoyance_esat)), "esat.prevoyance.compensation"))
    if sante_esat is not None:
        comp.append(_ligne_taux("compensation_sante", "Complémentaire santé", sante_esat, comp_sante,
                                c(sante_esat * pc(comp_sante)), "esat.complementaire_sante.compensation"))
    pat = compensables + autres
    retenues, charges, compensation = _somme(sal), _somme(pat), _somme(comp)
    signalements.append("Pas d'assurance chômage ni de réduction générale sur la rémunération garantie (CASF R. 243-9 ; CSS L. 241-13, II) ; part salariale de la CEG non due (commissions paritaires Agirc-Arrco).")
    signalements.append("Taxe sur les salaires, taxe d'apprentissage, participation à l'effort de construction et versement mobilité non retenus : la rémunération garantie n'est pas un salaire (CASF L. 243-5).")
    signalements.append("Contribution au dialogue social non due : assise sur les rémunérations des salariés (C. trav. L. 2135-15-1), ce que ne sont pas les travailleurs d'ESAT.")
    signalements.append("Contribution au plan de formation versée à l'opérateur de compétences (CASF L. 344-2-1, R. 243-9) non comprise : adhésion facultative, taux propre à l'opérateur, compensée en partie par l'État.")
    if sante_esat is None:
        signalements.append("Complémentaire santé non renseignée : non comprise.")
    if d["effectif"] is None:
        signalements.append("Effectif non renseigné : FNAL calculé pour 50 salariés et plus.")
    return {
        "salariales": sal, "patronales": pat, "compensation": comp,
        "net_travailleur": _dec.montant(rg + retenues), "cotisations_esat": _dec.montant(charges),
        "compensation_etat": _dec.montant(compensation), "cout_esat": _dec.montant(part + charges - compensation),
        "financement_etat": _dec.montant(aide + compensation),
    }
