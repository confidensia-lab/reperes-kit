"""Erreurs du client REPERES.

Une erreur ne contient jamais la clé API, la question posée ni le texte d'une réponse : seulement le
code HTTP et le code d'erreur public de l'API (`error`, `detail`, `upgrade_url`…).
"""
from __future__ import annotations


class ErreurReperes(Exception):
    """Erreur de l'API ou du client.

    Attributs : `statut_http` (code HTTP, `None` hors réponse HTTP), `code` (champ `error` de l'API),
    `detail`, `upgrade_url` (page des tarifs ou de souscription, quand l'API la donne).
    """

    def __init__(self, message: str, *, statut_http: int | None = None, code: str | None = None,
                 detail: str | None = None, upgrade_url: str | None = None):
        super().__init__(message)
        self.statut_http = statut_http
        self.code = code
        self.detail = detail
        self.upgrade_url = upgrade_url


class ErreurConfiguration(ErreurReperes):
    """Clé absente ou invalide, adresse de l'API invalide : rien n'a été envoyé."""


class ErreurRequete(ErreurReperes):
    """Corps ou paramètre refusé par l'API (400, 404, 413) ; `detail` dit lequel."""


class ErreurAuthentification(ErreurReperes):
    """Clé ou jeton absent, invalide ou révoqué (401)."""


class ErreurDroit(ErreurReperes):
    """Opération hors du droit du compte (403) ; `upgrade_url` mène à la page des tarifs."""


class CreditsEpuises(ErreurReperes):
    """Franchise du mois atteinte et crédits insuffisants (402).

    `credits_requis` : coût de l'opération ; `solde` : crédits disponibles.
    """

    def __init__(self, message: str, *, credits_requis: int | None = None, solde: int | None = None, **kw):
        super().__init__(message, **kw)
        self.credits_requis = credits_requis
        self.solde = solde


class DebitDepasse(ErreurReperes):
    """Débit dépassé (429) après les nouvelles tentatives ; `attente` : secondes conseillées."""

    def __init__(self, message: str, *, attente: int | None = None, **kw):
        super().__init__(message, **kw)
        self.attente = attente


class ServiceIndisponible(ErreurReperes):
    """API injoignable, délai dépassé ou moteur indisponible (502, 503) ; l'opération n'est pas comptée."""
