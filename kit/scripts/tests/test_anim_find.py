"""Tests for anim_find.py over a fake vault (a space in its path) with hand-written ANIM cards, Breakdowns and a
build note. Stdlib only; the real vault is never read.

    python -m unittest discover -s kit/scripts/tests -v
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import anim_find  # noqa: E402


def card(ID, cat, title, kind, rig, style, body, status="not-started"):
    return (f"---\naliases: []\ntags:\n  - roblox-dev\n  - asset/animation\n  - style/{style}\ntype: asset\n"
            f"asset_id: {ID}\ncategory: {cat}\nkind: {kind}\nrig_source: {rig}   # R6 | R15\n"
            f"user_note: \"none\"\nbreakdown_status: {status}\nstatus: draft\n---\n\n# {ID} — {title}\n\n"
            f"## What it is\n{body}\n\nTODO(analyst): fill in slam hitstop words that must not count.\n")


class TestFind(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="anim find "))
        self.vault = self.tmp / "fake vault"
        lib = self.vault / "11_ASSET_LIBRARY"
        docs = {
            "Animation/Combat/ANIM-COMBAT-0001.md": card("ANIM-COMBAT-0001", "combat", "Overhead hammer slam",
                                                         "video", "R15", "weighty",
                                                         "A two-handed overhead slam with a long hitstop."),
            "Animation/Combat/ANIM-COMBAT-0002.md": card("ANIM-COMBAT-0002", "combat", "Quick jab", "gif", "R6",
                                                         "anime", "A snappy jab on twos.", status="done"),
            "Animation/Weapon/ANIM-WEAPON-0001.md": card("ANIM-WEAPON-0001", "weapon", "Rifle reload", "video",
                                                         "R15", "realistic", "Magazine out, magazine in, bolt."),
            "Animation/Locomotion/ANIM-LOCO-0001.md": card("ANIM-LOCO-0001", "loco", "Stance walk loop", "roblox",
                                                           "R6", "stylized", "A walk cycle."),
            "Breakdowns/Breakdown_ANIM-COMBAT-0002.md": "---\ntags: []\n---\n# Breakdown\nThe recoil after "
                                                        "contact settles in four frames.\n",
            "Animation/_builds/ANIM-WEAPON-0001_Build_Notes.md": "# Build\nThe charging handle kick reads "
                                                                 "best at 3 frames.\n",
        }
        for rel, text in docs.items():
            p = lib / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        sheets = lib / "_media/anim/ANIM-COMBAT-0001/sheets"
        sheets.mkdir(parents=True)
        (sheets / "ANIM-COMBAT-0001_contact.jpg").write_bytes(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_find(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = anim_find.main(["--vault", str(self.vault), *args])
        return code, out.getvalue()

    def test_unknown_category_exits_2(self):
        # (critic B12) --cat bogus used to answer "no matches"
        code, out = self.run_find("slam", "--cat", "bogus", "--json")
        self.assertEqual(code, 2)
        doc = json.loads(out)
        self.assertIn("bogus", doc["error"])
        self.assertIn("combat", doc["categories"])
        code, out = self.run_find("slam", "--cat", "locomotion")         # aliases still work
        self.assertEqual(code, 0)

    def test_ranking(self):
        code, out = self.run_find("heavy slam with a freeze", "--json")
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res[0]["id"], "ANIM-COMBAT-0001")
        self.assertEqual(res[0]["category"], "combat")
        self.assertEqual(res[0]["breakdown_status"], "not-started")
        self.assertTrue(res[0]["sheet"].endswith("_contact.jpg"))
        self.assertTrue(res[0]["media_dir"])

    def test_breakdown_and_build_notes_are_searched(self):
        res = json.loads(self.run_find("recoil settles", "--json")[1])
        self.assertEqual(res[0]["id"], "ANIM-COMBAT-0002")
        self.assertTrue(res[0]["breakdown"])
        res = json.loads(self.run_find("charging handle", "--json")[1])
        self.assertEqual(res[0]["id"], "ANIM-WEAPON-0001")
        self.assertEqual(len(res[0]["builds"]), 1)

    def test_todo_text_not_indexed(self):
        res = json.loads(self.run_find("words", "--json")[1])
        self.assertEqual(res, [])

    def test_facets(self):
        res = json.loads(self.run_find("", "--cat", "combat", "--json")[1])
        self.assertEqual([r["id"] for r in res], ["ANIM-COMBAT-0001", "ANIM-COMBAT-0002"])
        res = json.loads(self.run_find("", "--rig", "r6", "--json")[1])
        self.assertEqual([r["id"] for r in res], ["ANIM-COMBAT-0002", "ANIM-LOCO-0001"])
        res = json.loads(self.run_find("", "--kind", "roblox", "--json")[1])
        self.assertEqual([r["id"] for r in res], ["ANIM-LOCO-0001"])
        res = json.loads(self.run_find("", "--style", "style/anime", "--json")[1])
        self.assertEqual([r["id"] for r in res], ["ANIM-COMBAT-0002"])
        res = json.loads(self.run_find("", "--cat", "locomotion", "--json")[1])
        self.assertEqual([r["id"] for r in res], ["ANIM-LOCO-0001"])
        res = json.loads(self.run_find("slam", "--cat", "weapon", "--json")[1])
        self.assertEqual(res, [])

    def test_k_and_text_output(self):
        res = json.loads(self.run_find("a", "--json")[1])
        self.assertEqual(len(res), 4)                        # stop words only: a facets-only listing, by id
        res = json.loads(self.run_find("reload jab walk slam", "--k", "2", "--json")[1])
        self.assertEqual(len(res), 2)
        code, out = self.run_find("reload")
        self.assertEqual(code, 0)
        self.assertIn("ANIM-WEAPON-0001", out)
        self.assertIn("card:", out)

    # ---------------------------------------------------------------- critic round 2
    def test_snippet_prefers_timing_row(self):
        bd = self.vault / "11_ASSET_LIBRARY/Breakdowns/Breakdown_ANIM-COMBAT-0001.md"
        bd.write_text("---\ntags: []\n---\n# Breakdown\nThe slam is the whole point of this clip.\n\n"
                      "| Phase | Frames | Note |\n|---|---|---|\n| Wind-up | 1–12 | slow lift |\n"
                      "| Slam contact | 13–15 | hitstop 4 f |\n", encoding="utf-8")
        res = json.loads(self.run_find("slam hitstop", "--json")[1])
        self.assertEqual(res[0]["id"], "ANIM-COMBAT-0001")
        self.assertEqual(res[0]["snippet"], "| Slam contact | 13–15 | hitstop 4 f |")
        code, out = self.run_find("slam hitstop")
        self.assertIn("match: | Slam contact | 13–15 | hitstop 4 f |", out)

    def test_snippet_prose_and_length(self):
        res = json.loads(self.run_find("recoil settles", "--json")[1])
        self.assertEqual(res[0]["snippet"], "The recoil after contact settles in four frames.")
        long = "word " * 60 + "flurry of punches " + "tail " * 60
        p = self.vault / "11_ASSET_LIBRARY/Animation/Combat/ANIM-COMBAT-0003.md"
        p.write_text(card("ANIM-COMBAT-0003", "combat", "Barrage", "video", "R15", "anime", long), encoding="utf-8")
        res = json.loads(self.run_find("flurry", "--json")[1])
        s = res[0]["snippet"]
        self.assertLessEqual(len(s), 160)
        self.assertIn("flurry", s)
        self.assertTrue(s.startswith("…") and s.endswith("…"))
        res = json.loads(self.run_find("", "--cat", "combat", "--json")[1])
        self.assertTrue(all(r["snippet"] is None for r in res))          # facets only: nothing to quote

    def test_paths_are_os_native(self):
        mixed = str(self.vault).replace("\\", "/")
        out = io.StringIO()
        with redirect_stdout(out):
            anim_find.main(["--vault", mixed, "slam", "--json"])
        r = json.loads(out.getvalue())[0]
        alt = "/" if os.sep == "\\" else "\\"
        for key in ("card", "media_dir", "sheet"):
            self.assertNotIn(alt, r[key], key)
            self.assertEqual(r[key], os.path.normpath(r[key]))

    def test_missing_vault(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = anim_find.main(["--vault", str(self.tmp / "nowhere"), "x", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out.getvalue()))

    def test_empty_library(self):
        empty = self.tmp / "empty vault"
        (empty / "11_ASSET_LIBRARY").mkdir(parents=True)
        out = io.StringIO()
        with redirect_stdout(out):
            code = anim_find.main(["--vault", str(empty), "slam"])
        self.assertEqual(code, 0)
        self.assertIn("No animation cards", out.getvalue())


if __name__ == "__main__":
    unittest.main()
