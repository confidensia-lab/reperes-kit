import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from reperes import ErreurConfiguration
from reperes import cli

from serveur import Gestionnaire, demarrer, programmer


class Commande(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur, cls.url = demarrer()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def setUp(self):
        programmer((200, {"delivery": "context", "metadata": {"retrieval": {"status": "ok"}}}))

    def lancer(self, *argv, cle="rpr_sk_test"):
        out, err = io.StringIO(), io.StringIO()
        env = {"REPERES_API_KEY": cle} if cle else {}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([*argv, "--base-url", self.url])
        return code, out.getvalue(), err.getvalue()

    def test_context_cle_et_exploration(self):
        code, out, _ = self.lancer("context", "  Projet de service ? ", "--exploration")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["delivery"], "context")
        v = Gestionnaire.vues[0]
        self.assertEqual((v["chemin"], v["auth"], v["corps"]), ("/api/v1/context", "Bearer rpr_sk_test", {"query": "Projet de service ?", "exploration": True}))

    def test_source_publique_sans_cle(self):
        code, _, _ = self.lancer("source", "a b/c", "--content", cle=None)
        self.assertEqual(code, 0)
        self.assertEqual(Gestionnaire.vues[0]["chemin"], "/sources/a%20b%2Fc/content")
        self.assertIsNone(Gestionnaire.vues[0]["auth"])

    def test_cle_absente_rien_n_est_envoye(self):
        code, _, err = self.lancer("precision", "Durée d'un CPOM ?", cle=None)
        self.assertEqual(code, 1)
        self.assertIn("REPERES_API_KEY", err)
        self.assertEqual(Gestionnaire.vues, [])

    def test_erreur_affichee_sans_secret(self):
        programmer((403, {"error": "forbidden", "upgrade_url": "https://reperes.test/tarifs#api"}))
        code, out, err = self.lancer("answer", "Question")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("HTTP 403 error=forbidden upgrade_url=https://reperes.test/tarifs#api", err)
        self.assertNotIn("rpr_sk_test", err)
        programmer((402, {"error": "credits_exhausted", "credits_required": 3, "credits_balance": 0}))
        code, _, err = self.lancer("context", "Question")
        self.assertEqual(code, 1)
        self.assertIn("credits_required=3", err)

    def test_livraison_degradee_affichee_mais_en_echec(self):
        programmer((200, {"delivery": "context", "metadata": {"retrieval": {"status": "unavailable"}}}))
        code, out, _ = self.lancer("context", "Question")
        self.assertEqual(code, 1)
        self.assertIn("unavailable", out)
        programmer((422, {"schema_version": "calcul.esat.v1", "statut": "erreur", "message": "date invalide"}))
        code, out, _ = self.lancer("esat", "--part", "30")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["statut"], "erreur")

    def test_valeur_identifiant_question_historique(self):
        programmer((200, {"schema_version": "etalon.result.v1", "status": "ok"}))
        self.assertEqual(self.lancer("valeur", "apa.domicile.plafond", "--date", "2026-03-01", "--coord", "gir=1")[0], 0)
        self.lancer("valeur", "valeur du point")
        self.lancer("valeur", "point.ccn66", "--historique")
        self.assertEqual([v["chemin"] for v in Gestionnaire.vues], [
            "/api/v1/valeurs/apa.domicile.plafond?date=2026-03-01&gir=1",
            "/api/v1/valeurs?q=valeur+du+point&resoudre=1",
            "/api/v1/valeurs/point.ccn66/historique",
        ])
        code, _, err = self.lancer("valeur", "valeur du point", "--historique")
        self.assertEqual(code, 1)
        self.assertIn("identifiant", err)
        code, _, err = self.lancer("valeur", "smic.horaire", "--coord", "gir")
        self.assertIn("Coordonnée invalide", err)
        programmer((200, {"schema_version": "etalon.result.v1", "status": "technical_error"}))
        self.assertEqual(self.lancer("valeur", "smic.horaire")[0], 1)

    def test_contrats_et_schema_publics(self):
        programmer((200, [{"nom": "calcul.esat.v1"}]))
        code, out, _ = self.lancer("contrats", cle=None)
        self.assertEqual((code, json.loads(out)), (0, [{"nom": "calcul.esat.v1"}]))
        programmer((200, {"title": "x"}))
        self.lancer("schema", "calcul.esat.v1", cle=None)
        self.assertEqual(Gestionnaire.vues[-1]["chemin"], "/api/v1/schemas/calcul.esat.v1.json")


def ns(**kw):
    base = dict(profil=None, convention="ccn66", emploi="educateur_specialise", date=None, anciennete=None, temps=None,
                etablissement=None, territoire=None, classement=None, oui=[], non=[], quantite=[], effectif=None, taux_atmp=None)
    base.update(kw)
    return argparse.Namespace(**base)


class Constructions(unittest.TestCase):
    def test_profil_depuis_les_options(self):
        p = cli.profil_remuneration(ns(anciennete="10", etablissement="mecs", oui=["surclassement_internat"], non=["prime_cer_cef"],
                                       quantite=["heures_dimanche_ferie=14"], effectif=120))
        self.assertEqual(p["reponses"], {"surclassement_internat": True, "prime_cer_cef": False})
        self.assertEqual(p["quantites"], {"heures_dimanche_ferie": "14"})
        self.assertEqual(p["employeur"], {"effectif": 120})

    def test_quantite_invalide_et_emploi_requis(self):
        with self.assertRaises(ErreurConfiguration):
            cli.profil_remuneration(ns(emploi="x", quantite=["nuits"]))
        with self.assertRaises(ErreurConfiguration):
            cli.profil_remuneration(ns(emploi=None))

    def test_demande_trajectoire(self):
        d = cli.demande_trajectoire(ns(emploi="moniteur_educateur", anciennete="0", etablissement="ime", debut=2016, fin=None,
                                       lecture="carriere", reference="2024-06"))
        self.assertEqual(d, {"profil": {"convention": "ccn66", "emploi": "moniteur_educateur", "anciennete_ans": "0", "type_etablissement": "ime"},
                             "debut": 2016, "lecture": "carriere", "reference": "2024-06"})

    def test_demande_esat(self):
        base = dict(effectif=None, sante_esat=None, sante_travailleur=None, prevoyance=None)
        d = cli.demande_esat(argparse.Namespace(part="30", euros=None, temps="0.8", date=None, **base))
        self.assertEqual(d, {"part_esat": {"pct_smic": "30"}, "temps_travail": "0.8"})
        with self.assertRaises(ErreurConfiguration):
            cli.demande_esat(argparse.Namespace(part="30", euros="400", temps=None, date=None, **base))

    def test_scenario_autonomie(self):
        cas = {"id": "x", "entree": {"date": "2026-01-15", "plan": {"taux_participation": "20"}, "realise": {"prix_horaire": "31"}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(cas, f)
        sc = cli.scenario_autonomie(argparse.Namespace(scenario=f.name, date="2025-01-15", prix="32", taux=None))
        self.assertEqual((sc["date"], sc["realise"]["prix_horaire"], sc["plan"]["taux_participation"]), ("2025-01-15", "32", "20"))
        with self.assertRaises(ErreurConfiguration):
            cli.scenario_autonomie(argparse.Namespace(scenario="/inexistant.json", date=None, prix=None, taux=None))
        self.assertTrue(cli.degrade({"statut": "erreur"}))
        self.assertFalse(cli.degrade({"statut": "partiel"}))


if __name__ == "__main__":
    unittest.main()
