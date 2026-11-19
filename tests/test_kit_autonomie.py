import json
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any

from reperes.kits import autonomie
from reperes.kits.valeurs import Instantane

CAS = Path(__file__).parent / "cas" / "autonomie"


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
        self.assertEqual(len(fichiers), 18)
        for f in fichiers:
            cas = json.loads(f.read_text(encoding="utf-8"))
            with self.subTest(cas=cas["id"]):
                attendu = json.loads((CAS / "sorties" / f"{cas['id']}.json").read_text(encoding="utf-8"))
                obtenu = autonomie.calculer(cas["entree"], instantane)
                self.assertIsNone(premier_ecart(obtenu, attendu))
                # Le résultat est sérialisable tel quel.
                self.assertEqual(json.loads(json.dumps(obtenu, ensure_ascii=False)), obtenu)


class Scenario(unittest.TestCase):
    def setUp(self):
        self.instantane = Instantane.charger(CAS / "instantane.json")
        self.base = json.loads((CAS / "01_fil_rouge_janvier_2026.json").read_text(encoding="utf-8"))["entree"]

    def test_nombres_en_texte_ou_en_nombre(self):
        nombre = json.loads(json.dumps(self.base))
        nombre["plan"]["aide_humaine"] = {"heures": 24, "tarif": 26.0}
        nombre["realise"].update({"heures_dans_plan": 20, "heures_hors_plan": "", "prix_horaire": "31,00"})
        texte = json.loads(json.dumps(self.base))
        texte["realise"]["heures_hors_plan"] = None
        self.assertEqual(autonomie.calculer(nombre, self.instantane), autonomie.calculer(texte, self.instantane))

    def test_erreurs_rendues_dans_le_resultat(self):
        for modif, message in (
            ({"date": "15/01/2026"}, "date invalide : 15/01/2026 (AAAA-MM-JJ)"),
            ({"personne": {"gir": 7}}, "GIR : de 1 à 6"),
            ({"realise": {"prix_horaire": "-1"}}, "les heures, tarifs, taux et montants sont positifs ou nuls"),
        ):
            r = autonomie.calculer({**self.base, **modif}, self.instantane)
            self.assertEqual((r["statut"], r["message"]), ("erreur", message))
            self.assertNotIn("periode", r)

    def test_scenario_illisible(self):
        for modif in ({"date": None}, {"personne": {"age": "82"}}, {"plan": {"forfait": None}},
                      {"realise": {"prix_horaire": True}}, {"besoin": {"provenance": "rumeur"}}):
            with self.assertRaises(autonomie.ScenarioInvalide):
                autonomie.calculer({**self.base, **modif}, self.instantane)

    def test_parametres_lus_dans_l_instantane(self):
        r = autonomie.calculer(self.base, self.instantane)
        self.assertTrue({v["parametre"] for v in r["valeurs"]} <= set(autonomie.PARAMETRES))


class Decimaux(unittest.TestCase):
    """Opérations du moteur : 96 bits de mantisse, 28 décimales au plus, demi au pair."""

    def test_division_au_plus_de_decimales(self):
        # 29 chiffres significatifs tiennent dans 96 bits ; le décimal Python à 28 chiffres en garde un de moins.
        self.assertEqual(autonomie.divise(Decimal(2550), Decimal("1.7")), Decimal(1500))
        self.assertEqual(autonomie.divise(Decimal(2000), Decimal("1.7")), Decimal("1176.4705882352941176470588235"))
        self.assertEqual(autonomie.divise(Decimal(1), Decimal(3)), Decimal("0.3333333333333333333333333333"))
        self.assertEqual(autonomie.divise(Decimal(2), Decimal(3)), Decimal("0.6666666666666666666666666667"))
        self.assertEqual(autonomie.divise(Decimal(20), Decimal(100)), Decimal("0.2"))

    def test_multiplication_et_addition_arrondies_au_pair(self):
        tiers = Decimal("0.3333333333333333333333333333")
        self.assertEqual(autonomie.fois(tiers, Decimal("0.5")), Decimal("0.1666666666666666666666666666"))
        self.assertEqual(autonomie.fois(Decimal("0.0000000000000000000000000025"), Decimal("0.1")),
                         Decimal("0.0000000000000000000000000002"))
        self.assertEqual(autonomie.plus(Decimal("7922816251426433759354395033.5"), Decimal("0.5")),
                         Decimal("7922816251426433759354395034"))
        self.assertEqual(autonomie.arrondi_pair(Decimal("17.07165"), 4), Decimal("17.0716"))


if __name__ == "__main__":
    unittest.main()
