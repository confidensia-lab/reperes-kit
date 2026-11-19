"""Décimal exact des kits, aligné sur le moteur REPERES (`reperes-calcul/src/dec.rs`).

Les montants et les taux ne passent jamais par un nombre flottant : lecture en `Decimal`, arrondi au
centime « demi au plus loin de zéro » (usage de la paie), écriture en texte.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

# Contexte de calcul : 28 chiffres significatifs, comme rust_decimal.
CONTEXTE = Context(prec=28, rounding=ROUND_HALF_UP)

CENTIME = Decimal("0.01")
QUATRE = Decimal("0.0001")
CENT = Decimal(100)


def parse(s: str) -> Decimal | None:
    """« 9.21 », « 9,21 », « 1 234,56 » → Decimal ; `None` si illisible."""
    t = "".join(c for c in s.strip() if not c.isspace() and c not in "  ").replace(",", ".")
    try:
        d = Decimal(t)
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def valeur(v: Any) -> Decimal | None:
    """Nombre écrit dans une valeur d'Étalon ou un scénario (texte ou nombre JSON)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        return parse(v)
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return parse(repr(v))
    return None


def texte(v: Any) -> str:
    """Texte d'une valeur scalaire (« 3 » pour 3, « ccn66 » pour "ccn66")."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def centime(d: Decimal) -> Decimal:
    """Arrondi au centime, demi au plus loin de zéro."""
    return d.quantize(CENTIME, rounding=ROUND_HALF_UP)


def quatre(d: Decimal) -> Decimal:
    return d.quantize(QUATRE, rounding=ROUND_HALF_UP)


def pct(d: Decimal) -> Decimal:
    """Pourcentage → fraction (9,21 → 0,0921)."""
    with localcontext(CONTEXTE):
        return d / CENT


def montant(d: Decimal) -> str:
    """Montant en texte, deux décimales (« 2345.60 »)."""
    return f"{centime(d):.2f}"


def nombre(d: Decimal) -> str:
    """Nombre en texte sans zéros inutiles (« 9.21 », « 434 »), comme `Decimal::normalize` en Rust."""
    n = d.normalize()
    if n == 0:
        return "0"
    s = format(n, "f")
    return s


def fr(d: Decimal, decimales: int) -> str:
    """Nombre à la française pour les libellés (« 1 234,56 », espace fine insécable)."""
    q = d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP) if decimales else d.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    s = f"{q:.{decimales}f}"
    ent, _, frac = s.partition(".")
    signe = "-" if ent.startswith("-") else ""
    chiffres = ent.lstrip("-")
    groupes = []
    while len(chiffres) > 3:
        groupes.insert(0, chiffres[-3:])
        chiffres = chiffres[:-3]
    groupes.insert(0, chiffres)
    e = " ".join(groupes)
    return f"{signe}{e},{frac}" if frac else f"{signe}{e}"
