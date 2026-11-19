import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reperes import ErreurReperes, Reperes, cli
from reperes.agent import Agent
from reperes.connexion import ConnexionAPI, ConnexionCLI, outils
from reperes.kits import KITS, creer_agent
from reperes.modeles import AppelOutil, Tour, texte_de
from reperes.outils import executer_par_api

from serveur import Gestionnaire, demarrer, programmer

SRC = str(Path(__file__).resolve().parents[1] / "src")
DEFS = [
    {"name": "reperes_valeur", "description": "Valeur officielle.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}},
    {"name": "reperes_context", "description": "Contexte.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "reperes_autonomie", "description": "APA.", "inputSchema": {"type": "object"}},
]


class ModeleScripte:
    """Modèle simulé : rend les tours programmés, garde les messages reçus."""

    def __init__(self, *tours):
        self.tours = list(tours)
        self.recus = []

    def repondre(self, messages, outils):
        self.recus.append((list(messages), [o.nom for o in outils]))
        return self.tours.pop(0)


class ConnexionFactice:
    def __init__(self, resultat=None):
        self.appels = []
        self.resultat = resultat or {"schema_version": "etalon.result.v1", "status": "ok", "valeurs": [{"valeur": "1682.30"}]}

    def definitions(self):
        return DEFS

    def executer(self, nom, arguments):
        self.appels.append((nom, arguments))
        return self.resultat


class Outils(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur, cls.url = demarrer()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def test_correspondance_des_outils_avec_l_api(self):
        programmer((200, {"ok": True}))
        c = Reperes("rpr_sk_test", base_url=self.url)
        executer_par_api(c, "reperes_valeur", {"id": "apa.domicile.plafond", "date": "2026-03-01", "coordonnees": {"gir": 1}})
        executer_par_api(c, "reperes_valeur", {"id": "point.ccn66", "historique": True})
        executer_par_api(c, "reperes_valeur", {"query": "plafond APA GIR 1"})
        executer_par_api(c, "reperes_calcul", {"convention": "esat", "part_esat": {"pct_smic": 30}})
        executer_par_api(c, "reperes_calcul", {"convention": "ccn66", "emploi": "educateur_specialise"})
        executer_par_api(c, "reperes_context", {"query": "Projet de service ?"})
        self.assertEqual([(v["methode"], v["chemin"]) for v in Gestionnaire.vues], [
            ("GET", "/api/v1/valeurs/apa.domicile.plafond?date=2026-03-01&gir=1"),
            ("GET", "/api/v1/valeurs/point.ccn66/historique"),
            ("GET", "/api/v1/valeurs?q=plafond+APA+GIR+1&resoudre=1"),
            ("POST", "/api/v1/calcul/esat"),
            ("POST", "/api/v1/calcul/remuneration"),
            ("POST", "/api/v1/context"),
        ])
        self.assertEqual(Gestionnaire.vues[3]["corps"], {"part_esat": {"pct_smic": 30}})
        with self.assertRaises(ErreurReperes):
            executer_par_api(c, "inconnu", {})

    def test_catalogue_du_simulateur_filtre_par_convention(self):
        programmer((200, {"schema_version": "calcul.modeles.v1", "conventions": [{"convention": "ccn66"}, {"convention": "ccn51"}]}))
        r = executer_par_api(Reperes("rpr_sk_test", base_url=self.url), "reperes_modeles", {"convention": "ccn51"})
        self.assertEqual(r["conventions"], [{"convention": "ccn51"}])

    def test_formats_des_fournisseurs(self):
        o = outils(ConnexionFactice(), ["reperes_valeur", "reperes_modeles"])
        self.assertEqual(o[0].pour_openai()["function"]["name"], "reperes_valeur")
        self.assertEqual(o[0].pour_anthropic()["input_schema"], DEFS[0]["inputSchema"])
        self.assertEqual(o[1].nom, "reperes_modeles")  # outil du framework, hors catalogue MCP
        with self.assertRaises(ErreurReperes):
            outils(ConnexionFactice(), ["reperes_inexistant"])

    def test_connexion_cli_en_sous_processus(self):
        env = {**os.environ, "PYTHONPATH": SRC, "REPERES_API_KEY": "rpr_sk_test", "REPERES_API_URL": self.url}
        c = ConnexionCLI([sys.executable, "-m", "reperes"], env=env)
        programmer((200, {"outils": DEFS}))
        self.assertEqual([d["name"] for d in c.definitions()], ["reperes_valeur", "reperes_context", "reperes_autonomie"])
        programmer((200, {"schema_version": "etalon.result.v1", "status": "ok"}))
        r = c.executer("reperes_valeur", {"id": "smic.horaire", "date": "2026-03-01"})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(Gestionnaire.vues[0]["chemin"], "/api/v1/valeurs/smic.horaire?date=2026-03-01")
        self.assertEqual(Gestionnaire.vues[0]["auth"], "Bearer rpr_sk_test")
        programmer((403, {"error": "forbidden"}))
        with self.assertRaises(ErreurReperes) as e:
            c.executer("reperes_answer", {"query": "Question"})
        self.assertIn("HTTP 403", str(e.exception))
        self.assertNotIn("rpr_sk_test", str(e.exception))


class AgentBoucle(unittest.TestCase):
    def test_outil_puis_reponse_et_garde_fou(self):
        modele = ModeleScripte(
            Tour(appels=[AppelOutil("a1", "reperes_valeur", {"id": "apa.domicile.plafond"})]),
            Tour(texte="Le plafond est de 1 682,30 € ; la participation est de 99,99 €."),
        )
        c = ConnexionFactice()
        agent = Agent(modele, outils(c, ["reperes_valeur"]), "Consignes.")
        r = agent.repondre("Quel plafond pour un GIR 2 ?")
        self.assertEqual(c.appels, [("reperes_valeur", {"id": "apa.domicile.plafond"})])
        self.assertEqual([a.nom for a in r.appels], ["reperes_valeur"])
        self.assertEqual(r.montants_non_sources, ["99.99"])
        self.assertTrue(r.termine)
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertIn("Règle de sourçage", agent.messages[0]["content"])
        self.assertEqual(modele.recus[0][1], ["reperes_valeur"])

    def test_montant_donne_par_l_utilisateur_n_est_pas_signale(self):
        agent = Agent(ModeleScripte(Tour(texte="Le service facture 29,00 € de l'heure.")), [], "C.")
        self.assertEqual(agent.repondre("Le service facture 29 € de l'heure.").montants_non_sources, [])

    def test_erreur_d_outil_rendue_au_modele_et_limite_d_appels(self):
        class Panne(ConnexionFactice):
            def executer(self, nom, arguments):
                raise ErreurReperes("HTTP 402 error=credits_exhausted")
        boucle = [Tour(appels=[AppelOutil(f"a{i}", "reperes_valeur", {})]) for i in range(3)]
        agent = Agent(ModeleScripte(*boucle), outils(Panne(), ["reperes_valeur"]), "C.", max_appels=3)
        r = agent.repondre("Question")
        self.assertFalse(r.termine)
        self.assertIn("credits_exhausted", agent.messages[3]["content"])

    def test_reprise_de_session(self):
        a = Agent(ModeleScripte(Tour(texte="Bonjour.")), [], "C.")
        a.repondre("Salut")
        b = Agent(ModeleScripte(Tour(texte="Suite.")), [], "C.", messages=json.loads(json.dumps(a.etat()))["messages"])
        b.repondre("Et ensuite ?")
        self.assertEqual([m["role"] for m in b.messages], ["system", "user", "assistant", "user", "assistant"])

    def test_texte_en_blocs(self):
        self.assertEqual(texte_de([{"type": "thinking", "thinking": "…"}, {"type": "text", "text": "Réponse"}]), "Réponse")


class Kits(unittest.TestCase):
    def test_kits_consignes_et_outils(self):
        self.assertEqual(set(KITS), {"apa", "remuneration", "esat"})
        for k in KITS.values():
            self.assertGreater(len(k.consignes), 200)
            for nom in k.outils:
                self.assertIn(nom, k.consignes + "reperes_modeles reperes_trajectoire reperes_context reperes_valeur")
        modele = ModeleScripte(Tour(texte="Bonjour."))
        agent = creer_agent("apa", ConnexionFactice(), modele, consignes_supplementaires="Département : Rhône.")
        agent.repondre("Bonjour")
        self.assertEqual(modele.recus[0][1], ["reperes_autonomie", "reperes_context", "reperes_valeur"])
        self.assertIn("fiches de terrain", agent.messages[0]["content"])
        self.assertIn("Département : Rhône.", agent.messages[0]["content"])


class CommandeAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur, cls.url = demarrer()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def lancer(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"REPERES_API_KEY": "rpr_sk_test", "REPERES_MODELE_URL": self.url, "REPERES_MODELE_CLE": "cle_modele"}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([*argv, "--base-url", self.url])
        return code, out.getvalue(), err.getvalue()

    def test_liste_des_kits(self):
        code, out, _ = self.lancer("agent", "--liste")
        self.assertEqual(code, 0)
        self.assertIn("apa", out)
        self.assertIn("remuneration", out)

    def test_un_tour_en_json_avec_session(self):
        reponse_modele = {"choices": [{"message": {"role": "assistant", "content": "Il faut le GIR notifié."}}]}
        with tempfile.TemporaryDirectory() as d:
            session = os.path.join(d, "s.json")
            programmer((200, {"outils": DEFS}), (200, reponse_modele))
            code, out, _ = self.lancer("agent", "apa", "--message", "Combien va payer ma mère ?", "--session", session, "--json")
            self.assertEqual(code, 0)
            r = json.loads(out)
            self.assertEqual((r["texte"], r["termine"], r["appels"]), ("Il faut le GIR notifié.", True, []))
            self.assertEqual([v["chemin"] for v in Gestionnaire.vues], ["/api/v1/mcp/outils", "/chat/completions"])
            self.assertEqual(Gestionnaire.vues[1]["auth"], "Bearer cle_modele")
            envoye = Gestionnaire.vues[1]["corps"]
            self.assertEqual([t["function"]["name"] for t in envoye["tools"]], ["reperes_autonomie", "reperes_context", "reperes_valeur"])
            s = json.loads(Path(session).read_text(encoding="utf-8"))
            self.assertEqual(s["kit"], "apa")
            self.assertEqual([m["role"] for m in s["messages"]], ["system", "user", "assistant"])
            code, _, err = self.lancer("agent", "esat", "--message", "Suite", "--session", session)
            self.assertEqual(code, 1)
            self.assertIn("appartient au kit apa", err)

    def test_outil_en_ligne_de_commande(self):
        programmer((200, {"schema_version": "etalon.result.v1", "status": "ok"}))
        code, out, _ = self.lancer("outil", "reperes_valeur", "--arguments", '{"id": "smic.horaire"}')
        self.assertEqual((code, json.loads(out)["status"]), (0, "ok"))
        code, _, err = self.lancer("outil", "reperes_valeur", "--arguments", "[1]")
        self.assertEqual(code, 1)
        self.assertIn("objet JSON", err)


if __name__ == "__main__":
    unittest.main()
