import json
import unittest
from pathlib import Path
from typing import Any

from reperes.kits import esat
from reperes.kits.valeurs import Instantane

CAS = Path(__file__).parent / "cas" / "esat"


def premier_ecart(a: Any, b: Any, chemin: str = "$") -> str | None:
    """Premier chemin JSON où `a` et `b` diffèrent (ordre des clés indifférent, ordre des listes significatif)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{chemin}.{k} : absent, attendu {b[k]!r}"
            if k not in b:
                return f"{chemin}.{k} : {a[k]!r}, attendu absent"
            e = premier_ecart(a[k], b[k], f"{chemin}.{k}")
            if e:
                return e
        return None
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            e = premier_ecart(x, y, f"{chemin}[{i}]")
            if e:
                return e
        if len(a) != len(b):
            return f"{chemin} : {len(a)} éléments, attendu {len(b)}"
        return None
    if type(a) is not type(b) or a != b:
        return f"{chemin} : {a!r}, attendu {b!r}"
    return None


class CasDeReference(unittest.TestCase):
    def test_sorties_du_moteur_reproduites(self):
        instantane = Instantane.charger(CAS / "instantane.json")
        fichiers = sorted(CAS.glob("[0-9][0-9]_*.json"))
        self.assertEqual(len(fichiers), 12)
        for f in fichiers:
            cas = json.loads(f.read_text(encoding="utf-8"))
            with self.subTest(cas=cas["id"]):
                attendu = json.loads((CAS / "sorties" / f"{cas['id']}.json").read_text(encoding="utf-8"))
                obtenu = esat.calculer(cas["entree"], instantane)
                self.assertIsNone(premier_ecart(obtenu, attendu))


class Demande(unittest.TestCase):
    def setUp(self):
        self.instantane = Instantane.charger(CAS / "instantane.json")

    def test_nombres_en_texte_ou_en_nombre(self):
        texte = esat.calculer({"date": "2026-07-15", "temps_travail": "0.8", "part_esat": {"pct_smic": "30"}}, self.instantane)
        nombre = esat.calculer({"date": "2026-07-15", "temps_travail": 0.8, "part_esat": {"pct_smic": 30}}, self.instantane)
        self.assertEqual(texte, nombre)

    def test_erreurs_rendues_dans_le_resultat(self):
        r = esat.calculer({"date": "15/07/2026", "part_esat": {"pct_smic": "20"}}, self.instantane)
        self.assertEqual((r["statut"], r["valeurs"]), ("erreur", []))
        r = esat.calculer({"date": "2026-07-15", "temps_travail": "1.2", "part_esat": {"pct_smic": "20"}}, self.instantane)
        self.assertEqual((r["statut"], r["temps_travail"]), ("erreur", "1.2"))
        r = esat.calculer({"date": "1990-01-01", "part_esat": {"pct_smic": "20"}}, self.instantane)
        self.assertEqual(r["statut"], "erreur")
        self.assertIn("valeurs d'Étalon absentes", r["message"])

    def test_demande_illisible_refusee(self):
        for d in ({"date": "2026-07-15"},
                  {"date": "2026-07-15", "part_esat": {"pct_smic": "vingt"}},
                  {"date": "2026-07-15", "effectif": "30", "part_esat": {"pct_smic": "20"}}):
            with self.assertRaises(esat.DemandeInvalide):
                esat.calculer(d, self.instantane)

    def test_date_absente_aujourd_hui_comme_l_api(self):
        import datetime
        r = esat.calculer({"part_esat": {"pct_smic": "20"}}, self.instantane)
        self.assertEqual(r["date"], datetime.date.today().isoformat())

    def test_parametres_suffisent_au_calcul(self):
        r = esat.calculer({"date": "2026-07-15", "effectif": 30, "part_esat": {"pct_smic": "35"},
                           "couverture": {"sante_esat": "20", "prevoyance_esat": "15"}}, self.instantane)
        self.assertLessEqual({v["parametre"] for v in r["valeurs"]}, set(esat.PARAMETRES))


if __name__ == "__main__":
    unittest.main()
