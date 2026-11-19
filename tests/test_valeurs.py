import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from reperes.kits import _dec
from reperes.kits.valeurs import Instantane, Lecteur

CAS = Path(__file__).parent / "cas"


class Decimaux(unittest.TestCase):
    def test_lectures_et_arrondis_comme_le_moteur(self):
        self.assertEqual(_dec.valeur("9,21"), Decimal("9.21"))
        self.assertEqual(_dec.valeur(7), Decimal(7))
        self.assertEqual(_dec.centime(Decimal("12.345")), Decimal("12.35"))
        self.assertEqual(_dec.centime(Decimal("-12.345")), Decimal("-12.35"))
        self.assertEqual(_dec.montant(Decimal(1)), "1.00")
        self.assertEqual(_dec.fr(Decimal("1234.56"), 2), "1 234,56")
        self.assertEqual(_dec.nombre(Decimal("9.210")), "9.21")
        self.assertEqual(_dec.nombre(Decimal("100")), "100")


class Lecture(unittest.TestCase):
    def test_lecture_datee_et_coordonnees(self):
        i = Instantane.depuis_json({"schema_version": "etalon.instantane.v1", "valeurs": {
            "smic.mensuel": [{"valeur": "1823.03", "valide_du": "2026-01-01", "territoire": "nat_FR"},
                             {"valeur": "1867.02", "valide_du": "2026-06-01", "territoire": "nat_FR"}],
            "cotisation.fnal": [{"valeur": "0.1", "valide_du": "2020-01-01", "coordonnees": {"effectif": "moins_de_50"}},
                                {"valeur": "0.5", "valide_du": "2020-01-01", "coordonnees": {"effectif": "50_et_plus"}}],
        }})
        self.assertEqual(i.lire("smic.mensuel", [], "2026-03-01").valeur, "1823.03")
        self.assertEqual(i.lire("smic.mensuel", [], "2026-11-16").valeur, "1867.02")
        self.assertEqual(i.lire("cotisation.fnal", [("effectif", "50_et_plus")], "2026-11-16").valeur, "0.5")
        self.assertIsNone(i.lire("cotisation.fnal", [], "2026-11-16"))
        lecteur = Lecteur(i)
        lecteur.valeur("smic.mensuel", [], "2026-11-16")
        lecteur.valeur("smic.mensuel", [], "2026-11-16")
        self.assertEqual(lecteur.utilisees(), [{"parametre": "smic.mensuel", "date": "2026-11-16", "valeur": "1867.02", "valide_du": "2026-06-01"}])

    def test_instantanes_des_cas_relus_et_resauves(self):
        for famille in ("autonomie", "esat"):
            brut = json.loads((CAS / famille / "instantane.json").read_text(encoding="utf-8"))
            i = Instantane.depuis_json(brut)
            self.assertGreater(len(i.valeurs), 3)
            with tempfile.TemporaryDirectory() as d:
                i.sauver(Path(d) / "i.json")
                j = Instantane.charger(Path(d) / "i.json")
            self.assertEqual(j.vers_json(), i.vers_json())


if __name__ == "__main__":
    unittest.main()
