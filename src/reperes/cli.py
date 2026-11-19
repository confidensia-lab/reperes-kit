"""Commande `reperes` : l'API REPERES en ligne de commande, au-dessus du SDK.

    export REPERES_API_KEY=rpr_sk_…
    reperes context "Quels repères pour construire un projet de service ?" --exploration
    reperes precision "Quelle est la durée maximale d'un CPOM ?"
    printf '%s' 'Ma question' | reperes context -
    reperes valeur smic.horaire --date 2025-03-01
    reperes valeur apa.domicile.plafond --coord gir=1
    reperes valeur "plafond APA GIR 1"            (question : valeur du paramètre retenu)
    reperes valeur point.ccn66 --historique
    reperes valeurs --q "valeur du point"         (paramètres candidats) ; --famille cotisations
    reperes remuneration ccn66 educateur_specialise --anciennete 10 --etablissement mecs --oui surclassement_internat
    reperes remuneration --modeles                 (conventions, emplois, types d'établissement)
    reperes trajectoire ccn66 moniteur_educateur --etablissement ime --lecture carriere --debut 2016
    reperes esat --part 30
    reperes autonomie scenario.json --prix 32      (démonstrateur APA ; un cas de référence est accepté)
    reperes source <id> --content                  (public)
    reperes contrats ; reperes schema calcul.esat.v1 ; reperes openapi   (publics)
    reperes outils                                 (outils pour un modèle, publics)
    reperes outil reperes_valeur --arguments '{"id": "smic.horaire"}'
    reperes agent apa                              (conversation ; --message pour un seul tour)
    reperes agent remuneration --message "…" --session s.json --json   (piloté par un autre agent)

Sortie : le JSON reçu sur stdout, seul ; les erreurs sur stderr (`--erreurs-json` : objet JSON
`{"error", "message", "statut_http", "detail", "upgrade_url"…}`), jamais la clé. Codes de sortie,
stables : 0 succès (y compris un statut métier : `not_found`, contexte vide) ; 1 échec sans résultat
(erreur HTTP ou réseau, clé absente, droit, crédits) ; 2 arguments invalides ; 3 résultat rendu mais
dégradé (recherche `unavailable`, précision `error`, valeur `technical_error`, simulation `erreur`), le
JSON restant sur stdout. Aucune invite interactive, sauf `reperes agent` sans `--message`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from . import __version__
from .client import URL_PAR_DEFAUT, Reperes
from .erreurs import ErreurConfiguration, ErreurReperes
from .outils import OUTILS_FRAMEWORK, executer_par_api

PARAMETRE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def degrade(resultat: Any) -> bool:
    """Livraison à ne pas confondre avec un succès : recherche en panne, statut d'erreur."""
    if not isinstance(resultat, dict):
        return False
    recherche = (resultat.get("metadata") or {}).get("retrieval") or {}
    return (recherche.get("status") == "unavailable" or resultat.get("status") in {"error", "technical_error"}
            or resultat.get("statut") == "erreur")


def coordonnees(paires: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in paires:
        k, sep, v = c.partition("=")
        if not sep or not k or not v:
            raise ErreurConfiguration(f"Coordonnée invalide : {c} (dimension=valeur attendu).")
        out[k] = v
    return out


def profil_remuneration(args: argparse.Namespace) -> dict:
    """Profil `calcul.remuneration.v1` depuis les options (un fichier `--profil` sert de base)."""
    profil: dict = {}
    if args.profil:
        try:
            with open(args.profil, encoding="utf-8") as f:
                profil = json.load(f)
        except (OSError, ValueError):
            raise ErreurConfiguration(f"Profil illisible : {args.profil}.") from None
        if not isinstance(profil, dict):
            raise ErreurConfiguration("Profil : objet JSON attendu.")
    for cle, valeur in (("convention", args.convention), ("emploi", args.emploi), ("date", args.date),
                        ("anciennete_ans", args.anciennete), ("temps_travail", args.temps),
                        ("type_etablissement", args.etablissement), ("territoire", args.territoire),
                        ("classement", args.classement)):
        if valeur is not None:
            profil[cle] = valeur
    for noms, oui in ((args.oui, True), (args.non, False)):
        for ident in noms:
            profil.setdefault("reponses", {})[ident] = oui
    for q in args.quantite:
        k, sep, v = q.partition("=")
        if not sep or not k or not v:
            raise ErreurConfiguration(f"Quantité invalide : {q} (identifiant=nombre attendu).")
        profil.setdefault("quantites", {})[k] = v
    employeur = profil.setdefault("employeur", {})
    if args.effectif is not None:
        employeur["effectif"] = args.effectif
    if args.taux_atmp is not None:
        employeur["taux_atmp"] = args.taux_atmp
    if not employeur:
        del profil["employeur"]
    if not profil.get("convention") or not profil.get("emploi"):
        raise ErreurConfiguration("Convention et emploi requis (voir `reperes remuneration --modeles`).")
    return profil


def demande_trajectoire(args: argparse.Namespace) -> dict:
    """Demande `calcul.trajectoire.v1` : profil des options (sans date), période, lecture, mois de
    référence des prix."""
    profil = profil_remuneration(args)
    profil.pop("date", None)
    demande: dict = {"profil": profil}
    for cle, valeur in (("debut", args.debut), ("fin", args.fin), ("lecture", args.lecture), ("reference", args.reference)):
        if valeur is not None:
            demande[cle] = valeur
    return demande


def demande_esat(args: argparse.Namespace) -> dict:
    """Demande `calcul.esat.v1` : part de l'ESAT en % du SMIC ou en euros du mois."""
    if (args.part is None) == (args.euros is None):
        raise ErreurConfiguration("Part de l'ESAT : --part (en % du SMIC) ou --euros (par mois), l'un des deux.")
    d: dict = {"part_esat": {"pct_smic": args.part} if args.part is not None else {"mensuelle": args.euros}}
    if args.date:
        d["date"] = args.date
    if args.temps is not None:
        d["temps_travail"] = args.temps
    if args.effectif is not None:
        d["effectif"] = args.effectif
    couverture = {k: v for k, v in (("sante_esat", args.sante_esat), ("sante_travailleur", args.sante_travailleur),
                                    ("prevoyance_esat", args.prevoyance)) if v is not None}
    if couverture:
        d["couverture"] = couverture
    return d


def scenario_autonomie(args: argparse.Namespace) -> dict:
    """Scénario `calcul.autonomie.v1` lu dans un fichier (ou `-` : entrée standard) ; les options
    modifient une hypothèse pour un rejeu."""
    try:
        if args.scenario == "-":
            sc = json.loads(sys.stdin.read())
        else:
            with open(args.scenario, encoding="utf-8") as f:
                sc = json.load(f)
    except (OSError, ValueError):
        raise ErreurConfiguration(f"Scénario illisible : {args.scenario}.") from None
    if isinstance(sc, dict) and isinstance(sc.get("entree"), dict):
        sc = sc["entree"]  # cas de référence : son entrée
    if not isinstance(sc, dict):
        raise ErreurConfiguration("Scénario : objet JSON attendu.")
    if args.date:
        sc["date"] = args.date
    if args.prix is not None:
        sc.setdefault("realise", {})["prix_horaire"] = args.prix
    if args.taux is not None:
        sc.setdefault("plan", {})["taux_participation"] = args.taux
    return sc


AIDE = {
    "context": "contexte sourcé, sans rédaction",
    "precision": "information ponctuelle et citation vérifiée",
    "answer": "réponse rédigée (option Génération ou crédits)",
    "valeur": "valeur de référence datée et sourcée (identifiant ou question)",
    "valeurs": "recherche ou catalogue des valeurs de référence",
    "remuneration": "simulation de rémunération conventionnelle (brut, net, coût employeur)",
    "trajectoire": "trajectoire d'une rémunération conventionnelle en euros courants et constants",
    "esat": "rémunération garantie d'un travailleur d'ESAT : part de l'ESAT et aide au poste",
    "autonomie": "démonstrateur APA à domicile : plan d'aide et reste à charge d'un mois",
    "source": "passeport de preuve d'un document (public)",
    "contrats": "contrats de réponse publiés (public)",
    "schema": "schéma JSON d'un contrat (public)",
    "openapi": "description OpenAPI de l'API (public)",
    "outils": "outils REPERES pour un modèle : définitions publiées (public)",
    "outil": "exécuter un outil REPERES : arguments JSON, résultat JSON",
    "agent": "agent d'un kit (apa, remuneration, esat) : conversation, ou un tour avec --message",
    "skills": "compétences Agent Skills des kits : liste, ou export pour un agent de code",
}


def analyseur() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reperes", description="L'API REPERES en ligne de commande.")
    parser.add_argument("--version", action="version", version=f"reperes {__version__}")
    sub = parser.add_subparsers(dest="commande", required=True)
    for commande, aide in AIDE.items():
        p = sub.add_parser(commande, help=aide)
        if commande in {"context", "precision", "answer"}:
            p.add_argument("query", help="question, ou - pour la lire sur l'entrée standard")
            if commande == "context":
                p.add_argument("--exploration", action="store_true", help="balayage documentaire élargi")
        elif commande == "source":
            p.add_argument("id", help="identifiant `sources[].id`")
            p.add_argument("--content", action="store_true", help="avec le texte du document")
        elif commande == "schema":
            p.add_argument("contrat", help="nom du contrat, ex. calcul.esat.v1")
        elif commande == "outil":
            p.add_argument("nom", help="nom de l'outil (voir `reperes outils`), ex. reperes_valeur")
            p.add_argument("--arguments", default="{}", help="arguments JSON, ou - pour les lire sur l'entrée standard")
            p.add_argument("--decrire", action="store_true", help="définition de l'outil (description, schéma des arguments), sans l'exécuter")
        elif commande == "agent":
            p.add_argument("kit", nargs="?", help="apa, remuneration ou esat (--liste pour la liste)")
            p.add_argument("--liste", action="store_true", help="kits disponibles")
            p.add_argument("--message", help="un seul tour : ce message, puis sortie (- : entrée standard)")
            p.add_argument("--session", help="fichier JSON de la conversation, repris et mis à jour à chaque tour")
            p.add_argument("--connexion", choices=["api", "cli"], default="api", help="REPERES par l'API (défaut) ou par la commande reperes")
            p.add_argument("--json", action="store_true", help="réponse JSON (texte, appels d'outils, montants non sourcés)")
            p.add_argument("--trace", action="store_true", help="affiche les appels d'outils sur la sortie d'erreur")
        elif commande == "skills":
            p.add_argument("--exporter", metavar="DOSSIER", help="copie les compétences dans DOSSIER (ex. .claude/skills)")
        elif commande == "valeur":
            p.add_argument("cible", help="identifiant (ex. smic.horaire) ou question en français")
            p.add_argument("--date", help="date de lecture AAAA-MM-JJ (défaut : aujourd'hui)")
            p.add_argument("--territoire", help="nat_FR (défaut), dep_976, dep_2A…")
            p.add_argument("--coord", action="append", default=[], help="coordonnée dimension=valeur (répétable)")
            p.add_argument("--historique", action="store_true", help="toutes les valeurs successives")
        elif commande == "valeurs":
            p.add_argument("--q", help="valeur cherchée, en français")
            p.add_argument("--famille", help="famille de paramètres (catalogue)")
        elif commande in {"remuneration", "trajectoire"}:
            p.add_argument("convention", nargs="?", help="ccn66, ccn51")
            p.add_argument("emploi", nargs="?", help="identifiant d'emploi (voir `reperes remuneration --modeles`)")
            p.add_argument("--profil", help="profil JSON complet (les options le complètent)")
            if commande == "remuneration":
                p.add_argument("--modeles", action="store_true", help="conventions, emplois et types d'établissement")
                p.add_argument("--date", help="date AAAA-MM-JJ (défaut : aujourd'hui)")
                p.add_argument("--anciennete", help="ancienneté retenue dans l'emploi, en années")
            else:
                p.set_defaults(date=None)
                p.add_argument("--anciennete", help="ancienneté la première année, en années")
                p.add_argument("--debut", type=int, help="première année (défaut 2014)")
                p.add_argument("--fin", type=int, help="dernière année (défaut : dernier IPC publié)")
                p.add_argument("--lecture", choices=["poste_constant", "carriere"], help="poste constant (défaut) ou carrière")
                p.add_argument("--reference", help="mois de référence des euros constants AAAA-MM")
            p.add_argument("--temps", help="part d'un temps plein (défaut 1)")
            p.add_argument("--etablissement", help="type d'établissement (ehpad, mecs, ime…)")
            p.add_argument("--territoire", help="nat_FR (défaut), dep_971…")
            p.add_argument("--classement", help="emploi de classement d'un emploi d'usage")
            p.add_argument("--oui", action="append", default=[], help="question à laquelle répondre oui (répétable)")
            p.add_argument("--non", action="append", default=[], help="question à laquelle répondre non (répétable)")
            p.add_argument("--quantite", action="append", default=[], help="élément variable identifiant=nombre (répétable)")
            p.add_argument("--effectif", type=int, help="effectif de l'entreprise")
            p.add_argument("--taux-atmp", dest="taux_atmp", help="taux AT/MP notifié (%%)")
        elif commande == "esat":
            p.add_argument("--part", help="part financée par l'ESAT, en %% du SMIC")
            p.add_argument("--euros", help="part financée par l'ESAT, en euros du mois")
            p.add_argument("--temps", help="part d'un temps plein (défaut 1)")
            p.add_argument("--date", help="date AAAA-MM-JJ (défaut : aujourd'hui)")
            p.add_argument("--effectif", type=int, help="effectif de l'organisme gestionnaire (FNAL)")
            p.add_argument("--sante-esat", dest="sante_esat", help="complémentaire santé, part de l'ESAT (€ par mois)")
            p.add_argument("--sante-travailleur", dest="sante_travailleur", help="complémentaire santé, part du travailleur (€ par mois)")
            p.add_argument("--prevoyance", help="prévoyance, cotisation de l'ESAT (€ par mois)")
        elif commande == "autonomie":
            p.add_argument("scenario", help="scénario JSON (ou cas de référence), - pour l'entrée standard")
            p.add_argument("--date", help="date de lecture des barèmes AAAA-MM-JJ")
            p.add_argument("--prix", help="tarif horaire facturé par le service")
            p.add_argument("--taux", help="taux de participation notifié (%%)")
        p.add_argument("--base-url", default=os.getenv("REPERES_API_URL") or URL_PAR_DEFAUT)
        p.add_argument("--timeout", type=float, default=180, help="secondes (défaut 180)")
        p.add_argument("--pretty", action="store_true", help="JSON indenté")
        p.add_argument("--erreurs-json", action="store_true", help="erreurs en JSON sur la sortie d'erreur (pilotage par un agent)")
    return parser


def executer(client: Reperes, args: argparse.Namespace, parser: argparse.ArgumentParser) -> Any:
    c = args.commande
    if c in {"context", "precision", "answer"}:
        question = (sys.stdin.read() if args.query == "-" else args.query).strip()
        if not question:
            parser.error("La question est vide.")
        if c == "context":
            return client.context(question, exploration=args.exploration)
        return client.precision(question) if c == "precision" else client.answer(question)
    if c == "valeur":
        cible = args.cible.strip()
        if not cible:
            parser.error("Identifiant ou question vide.")
        coords = coordonnees(args.coord)
        if PARAMETRE_RE.match(cible):
            if args.historique:
                return client.historique(cible, territoire=args.territoire, coordonnees=coords)
            return client.valeur(cible, date=args.date, territoire=args.territoire, coordonnees=coords)
        if args.historique:
            raise ErreurConfiguration("--historique exige un identifiant de paramètre (voir `reperes valeurs --q`).")
        return client.resoudre(cible, date=args.date, territoire=args.territoire, coordonnees=coords)
    if c == "valeurs":
        return client.rechercher(args.q, famille=args.famille)
    if c == "remuneration":
        return client.modeles() if args.modeles else client.remuneration(profil_remuneration(args))
    if c == "trajectoire":
        return client.trajectoire(demande_trajectoire(args))
    if c == "esat":
        return client.esat(demande_esat(args))
    if c == "autonomie":
        return client.autonomie(scenario_autonomie(args))
    if c == "source":
        if not args.id.strip():
            parser.error("Identifiant vide.")
        return client.source(args.id, contenu=args.content)
    if c == "contrats":
        return client.contrats()
    if c == "schema":
        return client.schema(args.contrat)
    if c == "outils":
        return [*client.outils_mcp(), *OUTILS_FRAMEWORK.values()]
    if c == "outil" and args.decrire:
        for d in [*client.outils_mcp(), *OUTILS_FRAMEWORK.values()]:
            if d.get("name") == args.nom:
                return d
        raise ErreurConfiguration(f"Outil inconnu : {args.nom} (voir `reperes outils`).")
    if c == "outil":
        brut = sys.stdin.read() if args.arguments == "-" else args.arguments
        try:
            arguments = json.loads(brut or "{}")
        except ValueError:
            raise ErreurConfiguration("Arguments : JSON invalide.") from None
        if not isinstance(arguments, dict):
            raise ErreurConfiguration("Arguments : objet JSON attendu.")
        return executer_par_api(client, args.nom, arguments)
    return client.openapi()


def agent(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """`reperes agent` : un kit en conversation, ou un tour par appel (pilotage par un autre agent)."""
    from .agent import AppelTrace
    from .connexion import ConnexionAPI, ConnexionCLI
    from .kits import KITS, creer_agent
    from .modeles import ModeleChat

    if args.liste or not args.kit:
        for k in KITS.values():
            print(f"{k.nom:13} {k.titre} : {k.description}")
        return 0
    if args.kit not in KITS:
        parser.error(f"kit inconnu : {args.kit} ({', '.join(KITS)})")

    def tracer(t: AppelTrace) -> None:
        etat = f"erreur : {t.erreur}" if t.erreur else "ok"
        print(f"  · {t.nom} {json.dumps(t.arguments, ensure_ascii=False)[:300]} → {etat}", file=sys.stderr)

    messages = None
    if args.session and os.path.exists(args.session):
        try:
            with open(args.session, encoding="utf-8") as f:
                session = json.load(f)
        except (OSError, ValueError):
            raise ErreurConfiguration(f"Session illisible : {args.session}.") from None
        if session.get("kit") != args.kit:
            raise ErreurConfiguration(f"La session {args.session} appartient au kit {session.get('kit')}.")
        messages = session.get("messages")
    connexion = ConnexionCLI() if args.connexion == "cli" else ConnexionAPI(Reperes(base_url=args.base_url, timeout=args.timeout))
    a = creer_agent(args.kit, connexion, ModeleChat(), trace=tracer if args.trace else None, messages=messages)

    def tour(message: str) -> int:
        r = a.repondre(message)
        if args.session:
            with open(args.session, "w", encoding="utf-8") as f:
                json.dump({**a.etat(), "kit": args.kit}, f, ensure_ascii=False, indent=1)
        if args.json:
            print(json.dumps(r.vers_json(), ensure_ascii=False, indent=2 if args.pretty else None))
        else:
            print(r.texte)
            if r.montants_non_sources:
                print(f"\n[À vérifier : montants sans résultat d'outil correspondant : {', '.join(r.montants_non_sources)}]", file=sys.stderr)
        return SUCCES if r.termine else DEGRADE

    if args.message is not None:
        message = (sys.stdin.read() if args.message == "-" else args.message).strip()
        if not message:
            parser.error("Message vide.")
        return tour(message)
    print(f"{KITS[args.kit].titre} (REPERES). Ligne vide pour quitter.\n", file=sys.stderr)
    while True:
        try:
            message = input("> ").strip()
        except EOFError:
            break
        if not message:
            break
        tour(message)
        print()
    return 0


#: Codes de sortie, stables : documentés pour le pilotage par un agent.
SUCCES, ECHEC, ARGUMENTS, DEGRADE = 0, 1, 2, 3


def signaler(exc: ErreurReperes, en_json: bool) -> None:
    """Erreur sur la sortie d'erreur : texte, ou objet JSON de forme stable (jamais la clé)."""
    if en_json:
        print(json.dumps({
            "error": exc.code or type(exc).__name__,
            "message": str(exc),
            "statut_http": exc.statut_http,
            "detail": exc.detail,
            "upgrade_url": exc.upgrade_url,
            **({"credits_requis": exc.credits_requis, "solde": exc.solde} if hasattr(exc, "credits_requis") else {}),
            **({"attente": exc.attente} if hasattr(exc, "attente") else {}),
        }, ensure_ascii=False), file=sys.stderr)
    else:
        print(str(exc), file=sys.stderr)


def skills(args: argparse.Namespace) -> int:
    from .kits import KITS, exporter_skills

    if args.exporter:
        for chemin in exporter_skills(args.exporter):
            print(chemin)
        return SUCCES
    for k in KITS.values():
        print(f"{k.skill:22} {k.titre} (kit `{k.nom}`)")
    return SUCCES


def main(argv: list[str] | None = None) -> int:
    parser = analyseur()
    args = parser.parse_args(argv)
    if args.commande in {"agent", "skills"}:
        try:
            return agent(args, parser) if args.commande == "agent" else skills(args)
        except ErreurReperes as exc:
            signaler(exc, args.erreurs_json)
            return ECHEC
    try:
        client = Reperes(base_url=args.base_url, timeout=args.timeout)
        resultat = executer(client, args, parser)
    except ErreurReperes as exc:
        signaler(exc, args.erreurs_json)
        return ECHEC
    print(json.dumps(resultat, ensure_ascii=False, indent=2 if args.pretty else None))
    return DEGRADE if degrade(resultat) else SUCCES
