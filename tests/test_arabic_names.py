"""Tests for arabic_names. Every name here is made up. Run: python3 -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from arabic_names import Hit, key, match, normalize  # noqa: E402


def rule(name, spelling):
    """The rule match() gives for `name` against one person spelled `spelling`, or None."""
    result = match([name], {"p": [spelling]})
    if name in result.matched:
        return result.matched[name].rule
    hits = result.review.get(name)
    return hits[0].rule if hits else None


class NormalizeTest(unittest.TestCase):
    def test_letter_forms_and_diacritics(self):
        self.assertEqual(normalize("أَحْمَد إبراهيم آل مـوسى"), "احمد ابراهيم ال موسي")
        self.assertEqual(normalize("فاطمة مؤمن هانئ"), "فاطمه مومن هاني")

    def test_persian_keyboard(self):
        self.assertEqual(normalize("ملک علی"), normalize("ملك علي"))

    def test_connectors_initials_and_titles(self):
        self.assertEqual(normalize("هيا بنت محمد بن سعد"), "هيا محمد سعد")
        self.assertEqual(normalize("د. نورة"), "نوره")
        self.assertEqual(normalize("Abdullah bin Saad"), "abdullah saad")

    def test_invisible_characters(self):
        self.assertEqual(normalize("‏نورة  محمد‬ "), "نوره محمد")

    def test_latin_punctuation(self):
        self.assertEqual(normalize("Sa'ad Al-Harbi"), "saad al harbi")

    def test_pdf_artifacts(self):
        self.assertEqual(normalize("االء عبدهللا"), "الاء عبدالله")
        self.assertEqual(normalize("ﻻما"), "لاما")  # lam-alef ligature

    def test_key_ignores_word_breaks(self):
        self.assertEqual(key("ريم عبد الرحمن"), key("ريم عبدالرحمن"))


class RuleTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(rule("نورة سعد الحربي", "نوره سعد الحربى"), "exact")

    def test_spacing(self):
        self.assertEqual(rule("ريم عبد الرحمن العمري", "ريم عبدالرحمن العمري"), "spacing")
        self.assertEqual(rule("دانة محمدالسبيعي", "دانة محمد السبيعي"), "spacing")

    def test_shorter_keeps_given_and_family(self):
        self.assertEqual(rule("مها الزهراني", "مها عايض سعد الزهراني"), "shorter")
        self.assertEqual(rule("مها عايض سعد الزهراني", "مها الزهراني"), "shorter")

    def test_shorter_three_parts(self):
        self.assertEqual(rule("مها عايض سعد", "مها عايض سعد الزهراني"), "shorter")

    def test_shorter_with_joined_parts(self):
        self.assertEqual(rule("وعد نور الدوسري", "وعدنور فهد الدوسري"), "shorter")

    def test_partial_given_and_father(self):
        self.assertEqual(rule("هيا محمد", "هيا محمد الشهري"), "partial")

    def test_latin(self):
        self.assertEqual(rule("خالد سعد الغامدي", "Khalid Saad Alghamdi"), "latin")
        self.assertEqual(rule("شهد فهد الشمري", "Shahad Fahad Alshammari"), "latin")
        self.assertEqual(rule("محمد علي الحربي", "Mohammed Ali Al-Harbi"), "latin")
        self.assertEqual(rule("سارة فهد القحطاني", "Sarah Fahad Algahtani"), "latin")
        self.assertEqual(rule("غادة عبدالله الشهري", "GHADA ABDULLAH SHAHRI"), "latin")
        self.assertEqual(rule("رهف سعد الجهني", "Rahaf Saad Alguhani"), "latin")
        self.assertEqual(rule("ماجد فهد الذهبي", "Maged Fahad Alzahabi"), "latin")
        self.assertEqual(rule("ظافر علي الشهري", "Dhafer Ali Alshehri"), "latin")

    def test_latin_keeps_letters_apart(self):
        self.assertIsNone(rule("جمال سعد الحربي", "Kamal Saad Alharbi"))
        self.assertIsNone(rule("حاتم سعد الحربي", "Hazim Saad Alharbi"))
        self.assertIsNone(rule("هشام سعد الحربي", "Husam Saad Alharbi"))

    def test_latin_partial(self):
        self.assertEqual(rule("هيا محمد الشهري", "HAYA ALSHAHRI"), "latin-partial")

    def test_typo_outside_given_name(self):
        self.assertEqual(rule("دانة خالد السبيعي", "دانة خالد السبعي"), "typo")
        self.assertEqual(rule("دانة خالد العتيبي", "دانة خالد العيتبي"), "typo")

    def test_different_people(self):
        for a, b in [
            ("لين خالد الحربي", "ليان خالد الحربي"),
            ("لمى محمد العتيبي", "مي محمد العتيبي"),
            ("سلمى أحمد الحربي", "سامي أحمد الحربي"),
            ("سعد عبده الغامدي", "سعد عبدالله الغامدي"),
            ("عبدالله محمد الحربي", "محمد عبدالله الحربي"),
            ("نورة علي", "نورة عبدالرحمن العتيبي"),
            ("نورة محمد الحربي", "نورة محمد العتيبي"),
            ("هيا", "هيا محمد الشهري"),
        ]:
            with self.subTest(a=a, b=b):
                self.assertIsNone(rule(a, b))


class MatchTest(unittest.TestCase):
    def test_strongest_rule_wins(self):
        result = match(
            ["نورة سعد الحربي"],
            {1: ["نورة الحربي"], 2: ["نورة سعد الحربي"]},
        )
        self.assertEqual(result.matched["نورة سعد الحربي"].person, 2)

    def test_ambiguous(self):
        result = match(["نورة الحربي"], {1: ["نورة سعد الحربي"], 2: ["نورة فهد الحربي"]})
        self.assertEqual([h.person for h in result.ambiguous["نورة الحربي"]], [1, 2])
        self.assertEqual(result.matched, {})

    def test_one_person_per_name(self):
        # The exact claim keeps the person; the other name is left for review.
        result = match(["نورة الحربي", "نورة سعد الحربي"], {1: ["نورة سعد الحربي"]})
        self.assertEqual(list(result.matched), ["نورة سعد الحربي"])
        self.assertEqual(result.unmatched, ["نورة الحربي"])
        self.assertEqual(result.review["نورة الحربي"], [Hit(1, "shorter", "نورة سعد الحربي")])

    def test_equal_claims_are_ambiguous(self):
        result = match(["نورة الحربي", "نورة سعد فهد"], {1: ["نورة سعد فهد الحربي"]})
        self.assertEqual(result.matched, {})
        self.assertEqual(set(result.ambiguous), {"نورة الحربي", "نورة سعد فهد"})

    def test_name_listed_twice(self):
        result = match(["نورة سعد الحربي", "نورة سعد الحربي"], {1: ["نورة سعد الحربي"]})
        self.assertIn("نورة سعد الحربي", result.ambiguous)
        self.assertEqual(result.matched, {})

    def test_review_is_not_applied(self):
        result = match(["هيا محمد الشهري"], {1: ["هيا محمد", "HAYA ALSHAHRI"]})
        self.assertEqual(result.matched, {})
        self.assertEqual(result.unmatched, ["هيا محمد الشهري"])
        self.assertEqual(
            [h.rule for h in result.review["هيا محمد الشهري"]], ["partial", "latin-partial"]
        )

    def test_latin_not_applied_when_arabic_given_name_disagrees(self):
        # "Ali" also reads as علا, and a brother shares the rest of the name.
        result = match(["علا محمد الحربي"], {1: ["علي محمد الحربي", "Ali Mohammed Alharbi"]})
        self.assertEqual(result.matched, {})
        self.assertEqual(result.review["علا محمد الحربي"][0].rule, "latin-partial")

    def test_latin_applied_when_arabic_family_name_differs(self):
        # Two family names: the clan in Arabic, the tribe in Latin.
        result = match(["جود فهد العنزي"], {1: ["جود فهد الرويلي", "Joud Fahad Alanzi"]})
        self.assertEqual(result.matched["جود فهد العنزي"].rule, "latin")

    def test_confirmed_is_applied_and_wins(self):
        result = match(
            ["نورة سعد الحربي", "نورة الحربي"],
            {1: ["نورة سعد الحربي"]},
            confirmed={"نورة الحربي": 1},
        )
        self.assertEqual(result.matched["نورة الحربي"], Hit(1, "confirmed", "نورة سعد الحربي"))
        # The exact claim loses to the confirmation and is left for review.
        self.assertEqual(result.unmatched, ["نورة سعد الحربي"])
        self.assertEqual(result.review["نورة سعد الحربي"][0].rule, "exact")

    def test_rejected_is_neither_applied_nor_suggested(self):
        result = match(
            ["مها الزهراني", "هيا محمد الشهري"],
            {1: ["مها عايض سعد الزهراني"], 2: ["هيا محمد"]},
            rejected={("مها الزهراني", 1), ("هيا محمد الشهري", 2)},
        )
        self.assertEqual(result.matched, {})
        self.assertEqual(result.review, {})

    def test_confirmed_must_be_valid(self):
        with self.assertRaises(ValueError):
            match(["نورة الحربي"], {1: ["نورة سعد الحربي"]}, confirmed={"نورة الحربي": 9})
        with self.assertRaises(ValueError):
            match(["نورة", "هيا"], {1: ["نورة سعد الحربي"]}, confirmed={"نورة": 1, "هيا": 1})

    def test_unmatched_and_empty(self):
        result = match(["", "هند سالم"], {1: ["نورة سعد الحربي"], 2: [""]})
        self.assertEqual(result.unmatched, ["", "هند سالم"])
        self.assertEqual(result.review, {})


if __name__ == "__main__":
    unittest.main()
