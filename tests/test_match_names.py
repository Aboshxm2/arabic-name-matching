"""Tests for scripts/match_names.py. Every name here is made up. Run: python3 -m unittest discover tests"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "match_names.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import xlsx_lite  # noqa: E402

FORMS_HEADER = ["ID", "Start time", "Completion time", "Email", "Name", "الاسم الثلاثي باللغة العربية", "البريد الالكتروني"]


class MatchNamesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        xlsx_lite.write_workbook(
            self.path("roster.xlsx"),
            [
                {"name": "ملاحظات", "rows": [["ملاحظة"], ["القائمة في الورقة التالية"]]},
                {
                    "name": "الأعضاء",
                    "rows": [
                        ["الفريق", "الاسم", "الرقم الجامعي"],
                        ["أ", "نورة سعد الحربي", ""],
                        ["أ", "هيا محمد الشهري", ""],
                        ["ب", "مها الزهراني", ""],
                        ["ب", "ريم عبدالرحمن العمري", "4500004"],
                        ["ب", "دانة خالد العتيبي", ""],
                        ["ب", "سارة علي الغامدي", "4500007"],
                        ["ب", "جود ناصر الدوسري", ""],
                    ],
                },
            ],
        )
        xlsx_lite.write_sheet(
            self.path("session 1(1-4).xlsx"),
            [
                FORMS_HEADER,
                ["1", "", "", "anonymous", "", "نوره سعد الحربى", "a1@uni.edu"],
                ["2", "", "", "a2@uni.edu", "HAYA ALSHAHRI", "هيا محمد", "a2@uni.edu"],
                ["3", "", "", "anonymous", "", "مها عايض سعد الزهراني", "a3@uni.edu"],
                ["4", "", "", "anonymous", "", "لمى فهد القحطاني", "a5@uni.edu"],
            ],
        )
        with open(self.path("session 2.csv"), "w", encoding="utf-8") as fh:
            fh.write("Timestamp,Full name,Email address,Student ID\n")
            fh.write("x,نورة الحربي,a1@uni.edu,\n")
            fh.write("x,ريم عبد الرحمن العمري,a4@uni.edu,4500004\n")
            fh.write("x,دانة خالد العيتبي,a6@uni.edu,\n")
            fh.write("x,ليلى فهد الدوسري,a7@uni.edu,4500007\n")

    def path(self, name):
        return os.path.join(self.dir, name)

    def run_script(self, *args):
        result = subprocess.run(
            [sys.executable, "-B", SCRIPT, *args], cwd=self.dir, capture_output=True, text=True
        )
        return result

    def match(self, *extra):
        result = self.run_script(
            "match", "--names", "roster.xlsx", "--names-sheet", "الأعضاء",
            "--people", "session 1(1-4).xlsx", "session 2.csv", "--out", "out.xlsx", "--lang", "en", *extra,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = xlsx_lite.read_sheet(self.path("out.xlsx"), 0)
        return result.stdout, {r[1]: r for r in rows[1:]}, rows[0]

    def test_inspect_marks_columns_without_showing_names(self):
        result = self.run_script("inspect", "session 1(1-4).xlsx", "session 2.csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("الاسم الثلاثي باللغة العربية  [4 values: 4 arabic]   <- name", result.stdout)
        self.assertIn("Name  [1 values: 1 latin]   <- account name", result.stdout)
        self.assertIn("Student ID  [2 values: 2 numbers]   <- student ID", result.stdout)
        self.assertNotIn("نوره", result.stdout)

    def test_results(self):
        out, results, header = self.match()
        status = {name: row[2] for name, row in results.items()}
        self.assertEqual(
            status,
            {
                "نورة سعد الحربي": "matched",
                "هيا محمد الشهري": "check",
                "مها الزهراني": "matched",
                "ريم عبدالرحمن العمري": "matched",
                "دانة خالد العتيبي": "check",
                "سارة علي الغامدي": "matched",
                "جود ناصر الدوسري": "not found",
            },
        )
        self.assertEqual(header[7:9], ["session 1", "session 2"])
        # Linked across both files by email, and shown under the fuller spelling.
        self.assertEqual(results["نورة سعد الحربي"][7:10], ["✓", "✓", "2"])
        self.assertEqual(results["ريم عبدالرحمن العمري"][5], "student ID")
        self.assertEqual(results["سارة علي الغامدي"][-1], "the ID matches but the name doesn't")
        self.assertIn('هيا محمد الشهري  ?  هيا محمد  [partial via "هيا محمد"; latin-partial via "HAYA ALSHAHRI"]  in 1 of 2 files', out)
        checks = xlsx_lite.read_sheet(self.path("out.xlsx"), 1)
        self.assertIn(
            ["هيا محمد الشهري", "هيا محمد", "", "only two names agree / Latin spelling, two names agree",
             "هيا محمد / HAYA ALSHAHRI", ""],
            checks,
        )
        self.assertIn("people in the files but not on the list: 3\n  دانة خالد العيتبي  in 1 of 2 files", out)

    def test_confirmations(self):
        with open(self.path("decisions.txt"), "w", encoding="utf-8") as fh:
            fh.write("# checked with the program office\n")
            fh.write("هيا محمد الشهري = a2@uni.edu\n")
            fh.write("دانة خالد العتيبي != دانة خالد العيتبي\n")
        out, results, _ = self.match("--confirmations", "decisions.txt")
        self.assertEqual(results["هيا محمد الشهري"][2:6], ["matched", "هيا محمد", "", "confirmed"])
        self.assertEqual(results["دانة خالد العتيبي"][2], "not found")
        self.assertIn("to check (possible matches, not applied): 0\n", out)

    def test_bad_confirmation_names_the_line(self):
        with open(self.path("decisions.txt"), "w", encoding="utf-8") as fh:
            fh.write("هيا محمد الشهري = nobody@uni.edu\n")
        result = self.run_script(
            "match", "--names", "roster.xlsx", "--names-sheet", "2", "--people", "session 1(1-4).xlsx",
            "--confirmations", "decisions.txt",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("line 1: 'nobody@uni.edu' matches no one in the files", result.stderr)

    def test_plain_text_list(self):
        with open(self.path("withdrawn.txt"), "w", encoding="utf-8") as fh:
            fh.write("# withdrew in week 2\nنورة الحربي\n\nمها الزهراني\n")
        result = self.run_script(
            "match", "--names", "withdrawn.txt", "--people", "session 1(1-4).xlsx", "session 2.csv", "--out", "w.xlsx",
            "--lang", "en",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = xlsx_lite.read_sheet(self.path("w.xlsx"), 0)
        self.assertEqual([(r[1], r[2], r[-2]) for r in rows[1:]], [("نورة الحربي", "matched", "2"), ("مها الزهراني", "matched", "1")])

    def test_list_given_as_a_file_too(self):
        result = self.run_script("match", "--names", "session 2.csv", "--people", "session 2.csv")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is both the list", result.stderr)


if __name__ == "__main__":
    unittest.main()
