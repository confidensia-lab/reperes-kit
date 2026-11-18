import os
import unittest
from unittest import mock

from reperes import (
    CreditsEpuises,
    DebitDepasse,
    ErreurAuthentification,
    ErreurConfiguration,
    ErreurDroit,
    ErreurRequete,
    Reperes,
    ServiceIndisponible,
)
from reperes._http import verifier_url

from serveur import Gestionnaire, demarrer, programmer


class Client(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur, cls.url = demarrer()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def client(self, cle="rpr_sk_test", **kw):
        return Reperes(cle, base_url=self.url, **kw)

    def test_valeur_rend_le_json_et_les_metadonnees(self):
        programmer((200, {"schema_version": "etalon.result.v1", "status": "ok"},
                    {"X-Reperes-Operation-Id": "op-1", "X-Reperes-Credits-Charged": "1", "X-Reperes-Credits-Remaining": "999"}))
        r = self.client().valeur("apa.domicile.plafond", date="2026-03-01", coordonnees={"gir": 1})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r.contrat, "etalon.result.v1")
        self.assertEqual((r.operation_id, r.credits_debites, r.credits_restants, r.statut_http), ("op-1", 1, 999, 200))
        v = Gestionnaire.vues[0]
        self.assertEqual((v["methode"], v["chemin"]), ("GET", "/api/v1/valeurs/apa.domicile.plafond?date=2026-03-01&gir=1"))
        self.assertEqual(v["auth"], "Bearer rpr_sk_test")
        self.assertTrue(v["agent"].startswith("reperes-python/"))

    def test_question_resolue_historique_recherche(self):
        programmer((200, {"status": "ambiguous"}))
        c = self.client()
        c.resoudre("valeur du point")
        c.historique("point.ccn66")
        c.rechercher("plafond APA")
        c.rechercher(famille="cotisations")
        self.assertEqual([v["chemin"] for v in Gestionnaire.vues], [
            "/api/v1/valeurs?q=valeur+du+point&resoudre=1",
            "/api/v1/valeurs/point.ccn66/historique",
            "/api/v1/valeurs?q=plafond+APA",
            "/api/v1/valeurs?famille=cotisations",
        ])

    def test_context_et_simulation_non_couverte(self):
        programmer((200, {"delivery": "context"}))
        self.client().context("  Projet de service ? ", exploration=True)
        self.assertEqual(Gestionnaire.vues[0]["corps"], {"query": "Projet de service ?", "exploration": True})
        programmer((422, {"schema_version": "calcul.remuneration.v1", "statut": "erreur", "message": "emploi inconnu"}))
        r = self.client().remuneration({"convention": "ccn66", "emploi": "x"})
        self.assertEqual((r.statut_http, r["statut"]), (422, "erreur"))

    def test_autonomie_accepte_un_cas_de_reference(self):
        programmer((200, {"statut": "ok"}))
        self.client().autonomie({"id": "x", "entree": {"periode": "2026-01"}})
        self.assertEqual(Gestionnaire.vues[0]["corps"], {"periode": "2026-01"})

    def test_erreurs_typees(self):
        cas = [
            (401, {"error": "unauthorized"}, ErreurAuthentification),
            (403, {"error": "forbidden", "upgrade_url": "https://reperes.test/tarifs#api"}, ErreurDroit),
            (400, {"error": "invalid_request", "detail": "`query` vide"}, ErreurRequete),
            (502, {"error": "engine_unavailable"}, ServiceIndisponible),
        ]
        for statut, corps, classe in cas:
            programmer((statut, corps))
            with self.assertRaises(classe) as e:
                self.client().precision("Durée d'un CPOM ?")
            self.assertEqual(e.exception.statut_http, statut)
            self.assertNotIn("rpr_sk_test", str(e.exception))
        programmer((402, {"error": "credits_exhausted", "credits_required": 3, "credits_balance": 1, "upgrade_url": "https://reperes.test/tarifs#api"}))
        with self.assertRaises(CreditsEpuises) as e:
            self.client().context("Question")
        self.assertEqual((e.exception.credits_requis, e.exception.solde, e.exception.code), (3, 1, "credits_exhausted"))
        self.assertEqual(e.exception.upgrade_url, "https://reperes.test/tarifs#api")

    def test_debit_depasse_puis_succes(self):
        attentes = []
        c = self.client(tentatives=2)
        c._t._dormir = attentes.append
        programmer((429, {"error": "rate_limited", "retry_after_seconds": 3}), (200, {"delivery": "context"}))
        self.assertEqual(c.context("Question")["delivery"], "context")
        self.assertEqual(attentes, [3])
        c0 = self.client(tentatives=0)
        programmer((429, {"error": "rate_limited", "retry_after_seconds": 7}))
        with self.assertRaises(DebitDepasse) as e:
            c0.context("Question")
        self.assertEqual(e.exception.attente, 7)

    def test_publics_sans_cle(self):
        programmer((200, [{"nom": "calcul.esat.v1"}]))
        with mock.patch.dict(os.environ, {}, clear=True):
            c = Reperes(base_url=self.url)
            self.assertEqual(c.contrats(), [{"nom": "calcul.esat.v1"}])
            programmer((200, {"title": "x"}))
            c.schema("calcul.esat.v1")
            c.source("a b/c", contenu=True)
            self.assertEqual([v["chemin"] for v in Gestionnaire.vues], ["/api/v1/schemas/calcul.esat.v1.json", "/sources/a%20b%2Fc/content"])
            self.assertTrue(all(v["auth"] is None for v in Gestionnaire.vues))
            with self.assertRaises(ErreurConfiguration):
                c.context("Question")

    def test_redirection_non_suivie_et_controles(self):
        programmer((302, None))
        with self.assertRaises(ErreurRequete):
            self.client().context("q")
        self.assertEqual(len(Gestionnaire.vues), 1)
        self.assertEqual(verifier_url("https://mcp.reperes.bmse.fr/"), "https://mcp.reperes.bmse.fr")
        for url in ("http://exemple.fr", "ftp://x", "https://u:p@x", "https://x?a=1", "x"):
            with self.assertRaises(ErreurConfiguration):
                verifier_url(url)
        with self.assertRaises(ErreurConfiguration):
            self.client(cle="rpr sk")
        with self.assertRaises(ErreurConfiguration):
            self.client().context("   ")


if __name__ == "__main__":
    unittest.main()
