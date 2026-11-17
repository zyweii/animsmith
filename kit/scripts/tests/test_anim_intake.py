"""Tests for anim_intake.py. Each test builds a throwaway fake vault (a space in its path) with inline templates
carrying the contract's placeholders and TODO(analyst) markers, seven category hubs and an index (CRLF, to check
line endings survive), plus synthetic media only. The real vault is never written. When ANIMSMITH_VAULT is set,
its two anim templates are copied (read-only) into the fake vault instead, so the real templates are exercised.

    python -m unittest discover -s kit/scripts/tests -v
"""

import importlib.util
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from PIL import Image

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import animlib  # noqa: E402
import anim_intake  # noqa: E402

_spec = importlib.util.spec_from_file_location("t_anim_analyze", HERE / "test_anim_analyze.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
REAL_VAULT = Path(os.environ["ANIMSMITH_VAULT"].strip().strip('"')) if os.environ.get("ANIMSMITH_VAULT") else None

CARD = """---
aliases: []
tags:
  - roblox-dev
  - asset/animation
  - {{CAT_TAG}}
type: asset
asset_id: {{ID}}
category: {{CATEGORY}}
kind: {{KIND}}
source: user-upload
source_file: "{{SOURCE_FILE}}"
rig_source: {{RIG}}
scale: {{SCALE}}
provenance: {{PROVENANCE}}   # own | licensed | third-party
user_note: "{{USER_NOTE}}"
received: {{DATE}}
duration_s: {{DURATION}}
fps: {{FPS}}
resolution: "{{RES}}"
frames: {{FRAMES}}
media_dir: "{{MEDIA_DIR}}"
spec_dir: "{{SPEC_DIR}}"
breakdown_status: not-started   # not-started | in-progress | done
last_updated: {{DATE}}
status: draft
---

# {{ID}} — {{TITLE}}

Hub: [[{{HUB}}]] · Breakdown: [[Breakdown_{{ID}}]]

## What it is
TODO(analyst): one paragraph.

## The user's note
> {{USER_NOTE}}

Provenance: `{{PROVENANCE}}`. Scale: `{{SCALE}}`.

## Media
Source: `{{SOURCE_FILE}}` ({{KIND}}, {{DURATION}} s at {{FPS}} fps, {{RES}}, {{FRAMES}} frames). Files: `{{MEDIA_DIR}}`.

{{SHEETS}}

## Measured numbers
{{NUMBERS_SUMMARY}}

## Verdict
```
Build: {{ID}} v### · Date: YYYY-MM-DD
```
Spec folder: `{{SPEC_DIR}}`
"""

BREAKDOWN = """---
aliases: []
tags:
  - roblox-dev
  - asset/breakdown
type: pipeline
asset_id: {{ID}}
last_updated: {{DATE}}
status: draft
---

# Breakdown — {{ID}}

Card: [[{{ID}}]] · Hub: [[{{HUB}}]]

## 1. What it is
TODO(analyst): one paragraph, then the user's note quoted: "{{USER_NOTE}}". Scale: `{{SCALE}}`.

## 2. Clip and camera
Source {{FPS}} fps · {{DURATION}} s · {{FRAMES}} frames · {{RES}} · rig {{RIG}}.

## 11. Transferable lessons
TODO(analyst): `<pattern> — evidence {{ID}} — proposed rule`.

## 13. Media
{{SHEETS}}
"""

HUB = ("---\ntags:\n  - roblox-dev\n---\n# {name}\n\n## Assets\n<!-- ANIM-CARDS:BEGIN -->\n<!-- ANIM-CARDS:END -->\n"
       "_No assets yet._\n\n## Related\n[[Asset_Library_Index]]\n")
INDEX = ("---\ntags:\n  - roblox-dev\n---\n# Index\n\n| ID | Cat | Title | Element | Style | Length | Breakdown | "
         "Recreation |\n|---|---|---|---|---|---|---|---|\n| [[ANIM-LOCO-0001]] | loco | Idle | none | stylized | "
         "6.0s @ 30.0 | done | attempted |\n<!-- ASSET-ROWS:END -->\n\n## Other\n")

_CUDA = None


def cuda_ok():
    """True when ffmpeg can decode H.264 with -hwaccel cuda here (the tests then run the GPU path)."""
    global _CUDA
    if _CUDA is None:
        _CUDA = False
        if HAS_FFMPEG:
            tmp = Path(tempfile.mkdtemp(prefix="anim cuda "))
            try:
                clip = tmp / "c.mp4"
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                "testsrc=size=64x64:rate=10:duration=1", "-pix_fmt", "yuv420p", str(clip)],
                               capture_output=True)
                r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-hwaccel", "cuda", "-i", str(clip),
                                    "-f", "null", "-"], capture_output=True, text=True, errors="replace")
                _CUDA = r.returncode == 0 and not animlib._GPU_FAIL.search(r.stderr or "")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return _CUDA


def GPU():
    return "on" if cuda_ok() else "off"


def make_vault(root, crlf_hub="combat"):
    lib = root / "11_ASSET_LIBRARY"
    tpl = root / "_meta" / "templates"
    tpl.mkdir(parents=True)
    for name, text in (("Template_Anim_Asset_Card.md", CARD), ("Template_Anim_Breakdown.md", BREAKDOWN)):
        src = REAL_VAULT / "_meta" / "templates" / name if REAL_VAULT else None
        if src is not None and src.is_file():
            shutil.copy2(src, tpl / name)       # read-only copy of the real template
        else:
            (tpl / name).write_text(text, encoding="utf-8")
    for cat, meta in animlib.CATEGORIES.items():
        (lib / meta["folder"]).mkdir(parents=True, exist_ok=True)
        text = HUB.format(name=meta["hub"])
        if cat == crlf_hub:
            text = text.replace("\n", "\r\n")
        (lib / f"{meta['hub']}.md").write_bytes(text.encode("utf-8"))
    (lib / "Asset_Library_Index.md").write_bytes(INDEX.replace("\n", "\r\n").encode("utf-8"))
    ids = {m["prefix"]: 0 for m in animlib.CATEGORIES.values()}
    animlib.write_json(lib / "Animation" / "_ids.json", ids)
    (lib / "_inbox" / "anim").mkdir(parents=True)
    (lib / "_inbox" / "anim" / "README.md").write_text("# How to drop clips here\n", encoding="utf-8")
    return root


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def fake_catalog(suspicious=()):
    def track(vals):
        return [{"f": f, "r": r, "e": "Linear", "d": "In"} for f, r in vals]

    def seq(name, rig="R15"):
        return {"name": name, "path_in_file": f"Pack/{name}", "length_s": 1.0, "fps_guess": 30, "loop": False,
                "priority": "Action", "parts": ["RightUpperArm", "UpperTorso"],
                "markers": [{"name": "Hit", "t": 0.4}],
                "spec": {"version": 1, "name": name, "rig": rig, "space": "rel", "fps": 30, "length": 30,
                         "loop": False, "priority": "Action", "markers": [{"name": "Hit", "f": 12}],
                         "tracks": {"RightUpperArm": track([(0, [0, 0, 0]), (10, [-30, 0, 0]),
                                                            (12, [90, 0, 0]), (30, [0, 0, 0])]),
                                    "UpperTorso": track([(0, [0, 0, 0]), (12, [0, 20, 0]), (30, [0, 0, 0])])}}}

    mod = types.ModuleType("anim_catalog")
    mod.extract = lambda path: {"scan": {"scripts": len(suspicious), "suspicious": list(suspicious)},
                                "sequences": [seq("Punch_Jab"), seq("Punch_Cross")]}
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="anim intake "))   # a space in the path, on purpose
        self.vault = make_vault(self.tmp / "fake vault")
        self.lib = self.vault / "11_ASSET_LIBRARY"
        self.inbox = self.lib / "_inbox" / "anim"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_intake(self, *extra, gpu=None):
        out, err = io.StringIO(), io.StringIO()
        args = ["--vault", str(self.vault), "--json", "--gpu", gpu or GPU(), *extra]
        with redirect_stdout(out), redirect_stderr(err):
            code = anim_intake.main(args)
        try:
            doc = json.loads(out.getvalue())
        except ValueError:
            self.fail(f"no JSON on stdout: {out.getvalue()!r} {err.getvalue()!r}")
        return code, doc

    def clip(self, folder, name="heavy_slam.mp4", note=None, n=45):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        fr = synth.square_clip(self.tmp / f"frames {name}", n=n)
        p = synth.encode(fr, folder / name, fps=30)
        if note is not None:
            (folder / (name + ".txt")).write_text(note, encoding="utf-8")
        return p


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
class TestVideo(Base):
    def test_file_video_from_category_folder(self):
        src = self.clip(self.inbox / "combat", note="Heavy slam test. I like how it lands; it's my own move.")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        res = [r for r in doc["results"] if r["kind"] != "skip"]
        self.assertEqual(len(res), 1, doc["results"])
        r = res[0]
        self.assertEqual((r["id"], r["kind"], r["category"]), ("ANIM-COMBAT-0001", "video", "combat"))
        # (critic r2) own work, but the note doesn't ask for a faithful copy: absolute scale
        self.assertEqual((r["scale"], r["provenance"], r["provenance_guess"]), ("absolute", "own", "clear"))
        self.assertIn("my own move", r["user_note"])
        self.assertFalse(r["inbox_kept"])
        self.assertEqual(doc["gpu"], GPU() == "on")
        mdir = self.lib / "_media/anim/ANIM-COMBAT-0001"
        for sub in ("source", "frames", "sheets", "analysis"):
            self.assertTrue((mdir / sub).is_dir(), sub)
        self.assertTrue((mdir / "source" / "heavy_slam.mp4").is_file())
        self.assertTrue((mdir / "source" / "heavy_slam.mp4.txt").is_file())     # (critic r2) the sidecar too
        self.assertFalse(src.exists())                                    # moved out of the inbox
        self.assertFalse((self.inbox / "combat" / "heavy_slam.mp4.txt").exists())
        self.assertTrue((self.inbox / "README.md").is_file())             # README never touched
        self.assertEqual(len(r["sheets"]), 5)
        for s in r["sheets"]:
            self.assertTrue(Path(s).is_file(), s)
        self.assertTrue(1 <= len(r["frames"]) <= 6)
        for f in r["frames"]:
            self.assertTrue(Path(f).is_file(), f)
        nums = json.loads(Path(r["numbers"]).read_text(encoding="utf-8"))
        self.assertTrue(synth.near(nums["peaks"], synth.SQ_PEAK), nums["peaks"])
        self.assertTrue(nums["camera"]["moving"])
        self.assertTrue(nums["decode"].startswith("gpu" if GPU() == "on" else "cpu"))
        card = Path(r["card"]).read_text(encoding="utf-8")
        bd = Path(r["breakdown"]).read_text(encoding="utf-8")
        self.assertEqual(Path(r["card"]).parent, self.lib / "Animation/Combat")
        for text in (card, bd):
            self.assertNotIn("{{", text)
            self.assertIn("TODO(analyst)", text)
            self.assertIn("ANIM-COMBAT-0001", text)
        self.assertIn("category: combat", card)
        self.assertIn("asset/combat", card)
        self.assertIn("provenance: own", card)
        self.assertIn("![[ANIM-COMBAT-0001_contact.jpg]]", card)
        self.assertIn("[[Category_Combat_Animation]]", card)
        self.assertIn("> Heavy slam test.", card)
        self.assertIn('user_note: "Heavy slam test.', card)
        self.assertTrue((self.lib / "Animation/_specs/ANIM-COMBAT-0001").is_dir())
        hub = (self.lib / "Category_Combat_Animation.md").read_bytes().decode("utf-8")
        self.assertIn("\r\n", hub)
        self.assertNotIn("\n", hub.replace("\r\n", ""))                    # CRLF kept everywhere
        self.assertNotIn("_No assets yet._", hub)
        lines = hub.split("\r\n")
        i = lines.index("<!-- ANIM-CARDS:END -->")
        self.assertTrue(lines[i - 1].startswith("- [[ANIM-COMBAT-0001]] — Heavy slam · video · breakdown "
                                                "not-started"), lines[i - 1])
        idx = (self.lib / "Asset_Library_Index.md").read_bytes().decode("utf-8")
        rows = idx.split("\r\n")
        j = rows.index("<!-- ASSET-ROWS:END -->")
        self.assertTrue(rows[j - 1].startswith("| [[ANIM-COMBAT-0001]] | combat | Heavy slam | — | — | "), rows[j - 1])
        self.assertTrue(rows[j - 1].endswith("| not-started | none |"))
        ids = json.loads((self.lib / "Animation/_ids.json").read_text(encoding="utf-8"))
        self.assertEqual(ids["ANIM-COMBAT"], 1)

    def test_category_from_note_and_title(self):
        self.clip(self.inbox, name="clip_a.mp4", note="reaction: Gut punch flinch\nthe snap back is great")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertEqual((r["id"], r["category"], r["title"]), ("ANIM-REACTION-0001", "reaction",
                                                                 "Gut punch flinch"))
        self.assertEqual(r["provenance"], "third-party")
        self.assertEqual(r["scale"], "absolute")

    def test_no_category_skips(self):
        src = self.clip(self.inbox, name="mystery.mp4", note="I like the timing")
        code, doc = self.run_intake()
        self.assertEqual(code, 0)
        r = next(x for x in doc["results"] if x["file"].endswith("mystery.mp4"))
        self.assertEqual((r["kind"], r["reason"]), ("skip", "no category"))
        self.assertTrue(src.is_file())
        self.assertFalse((self.lib / "_media/anim").exists() and any((self.lib / "_media/anim").iterdir()))

    def test_files_outside_inbox_are_copied(self):
        src = self.clip(self.tmp / "elsewhere dir", name="dash.mp4")
        code, doc = self.run_intake("--files", str(src), "--category", "loco", "--rig", "r6")
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertEqual(r["id"], "ANIM-LOCO-0001")
        self.assertEqual(r["rig"], "R6")
        self.assertTrue(src.is_file())                                     # copied, not moved

    def test_dry_run_writes_nothing(self):
        self.clip(self.inbox / "weapon", name="reload.mp4")
        self.clip(self.inbox / "weapon", name="reload_b.mp4")
        before = snapshot(self.vault)
        code, doc = self.run_intake("--dry-run")
        self.assertEqual(code, 0, doc)
        self.assertEqual(snapshot(self.vault), before)
        ids = [r["id"] for r in doc["results"] if r.get("dry_run")]
        self.assertEqual(ids, ["ANIM-WEAPON-0001", "ANIM-WEAPON-0002"])
        self.assertTrue(doc["dry_run"])

    def test_rollback_on_failure(self):
        src = self.clip(self.inbox / "combat", note="combat thing")
        before = snapshot(self.vault)
        with mock.patch.object(anim_intake, "_post_success_hook", side_effect=RuntimeError("boom")):
            code, doc = self.run_intake()
        self.assertEqual(code, 1)
        self.assertEqual(doc["results"][0]["kind"], "error")
        self.assertIn("boom", doc["results"][0]["reason"])
        self.assertTrue(src.is_file())
        self.assertEqual(snapshot(self.vault), before)

    def test_ids_never_reused(self):
        self.clip(self.inbox / "combat", name="one.mp4")
        code, doc = self.run_intake()
        self.assertEqual(doc["results"][0]["id"], "ANIM-COMBAT-0001")
        # the user deletes everything about it by hand
        shutil.rmtree(self.lib / "_media/anim/ANIM-COMBAT-0001")
        shutil.rmtree(self.lib / "Animation/_specs/ANIM-COMBAT-0001")
        (self.lib / "Animation/Combat/ANIM-COMBAT-0001.md").unlink()
        (self.lib / "Breakdowns/Breakdown_ANIM-COMBAT-0001.md").unlink()
        self.clip(self.inbox / "combat", name="two.mp4")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["results"][0]["id"], "ANIM-COMBAT-0002")

    def test_gpu_failure_exit_4_then_gpu_off(self):
        src = self.clip(self.inbox / "combat", name="gpu.mp4")
        before = snapshot(self.vault)
        with mock.patch.dict(os.environ, {"ANIMSMITH_HWACCEL": "not_a_real_accel"}):
            code, doc = self.run_intake(gpu="on")
            self.assertEqual(code, 4, doc)
            self.assertTrue(doc["error"].startswith("gpu_failed"))
            self.assertEqual(doc["results"][0]["kind"], "error")
            self.assertTrue(src.is_file())
            self.assertEqual(snapshot(self.vault), before)
            code, doc = self.run_intake(gpu="off")             # only when the user says so
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["results"][0]["id"], "ANIM-COMBAT-0001")
        self.assertFalse(doc["gpu"])

    def test_refile(self):
        self.clip(self.inbox / "combat", name="flinch.mp4", note="combat: Flinch on hit")
        code, doc = self.run_intake()
        old = doc["results"][0]["id"]
        self.assertEqual(old, "ANIM-COMBAT-0001")
        other = self.vault / "10_CRAFT" / "Some study.md"            # a note elsewhere that links the reference
        other.parent.mkdir(parents=True)
        other.write_bytes(("See [[ANIM-COMBAT-0001]], [[Breakdown_ANIM-COMBAT-0001|its breakdown]] and "
                           "[[ANIM-COMBAT-00012]].\r\n").encode("utf-8"))
        code, doc = self.run_intake("--refile", old, "--category", "reaction", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(doc["results"][0]["id"], "ANIM-REACTION-0001")
        self.assertTrue((self.lib / "Animation/Combat/ANIM-COMBAT-0001.md").is_file())
        code, doc = self.run_intake("--refile", old, "--category", "reaction")
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        new = "ANIM-REACTION-0001"
        self.assertEqual((r["id"], r["refiled_from"], r["category"]), (new, old, "reaction"))
        self.assertFalse((self.lib / "Animation/Combat" / f"{old}.md").exists())
        self.assertFalse((self.lib / "Breakdowns" / f"Breakdown_{old}.md").exists())
        self.assertFalse((self.lib / "_media/anim" / old).exists())
        self.assertFalse((self.lib / "Animation/_specs" / old).exists())
        card = (self.lib / "Animation/Reaction" / f"{new}.md").read_text(encoding="utf-8")
        self.assertIn(f"aliases: [{old}]", card)                           # the old ID resolves to the new card
        self.assertNotIn(old, card.replace(f"aliases: [{old}]", ""))
        self.assertEqual(other.read_bytes().decode("utf-8"),
                         f"See [[{new}]], [[Breakdown_{new}|its breakdown]] and [[ANIM-COMBAT-00012]].\r\n")
        self.assertIn(str(other), r["links_rewritten"])
        self.assertIn("category: reaction", card)
        self.assertIn("asset/reaction", card)
        self.assertIn("[[Category_Reaction_Animation]]", card)
        bdt = (self.lib / "Breakdowns" / f"Breakdown_{new}.md").read_text(encoding="utf-8")
        self.assertIn(f"aliases: [Breakdown_{old}]", bdt)
        self.assertNotIn(old, bdt.replace(f"aliases: [Breakdown_{old}]", ""))
        mdir = self.lib / "_media/anim" / new
        self.assertTrue((mdir / "sheets" / f"{new}_contact.jpg").is_file())
        nums = json.loads((mdir / "analysis/numbers.json").read_text(encoding="utf-8"))
        self.assertEqual(nums["id"], new)
        self.assertTrue((self.lib / "Animation/_specs" / new).is_dir())
        self.assertNotIn(old, (self.lib / "Category_Combat_Animation.md").read_text(encoding="utf-8"))
        self.assertIn(f"- [[{new}]] — Flinch on hit", (self.lib / "Category_Reaction_Animation.md").read_text(
            encoding="utf-8"))
        idx = (self.lib / "Asset_Library_Index.md").read_bytes().decode("utf-8")
        self.assertNotIn(old, idx)
        self.assertIn(f"| [[{new}]] | reaction | Flinch on hit |", idx)
        ids = json.loads((self.lib / "Animation/_ids.json").read_text(encoding="utf-8"))
        self.assertEqual((ids["ANIM-COMBAT"], ids["ANIM-REACTION"]), (1, 1))   # the old id stays used
        self.assertEqual(animlib.next_id(self.vault, "combat"), "ANIM-COMBAT-0002")

    def _fake_tools(self, problem_notes):
        tools = self.vault / "_meta/tools"
        tools.mkdir(parents=True, exist_ok=True)
        (tools / "build_mocs.py").write_text("print('mocs ok')\n", encoding="utf-8")
        body = "".join(f"print({('- ' + n)!r})\nprint('    only 2 distinct links (<8)')\n" for n in problem_notes)
        (tools / "validate_vault.py").write_text(
            "import sys\nassert sys.argv[1:] == ['--folder', '11_ASSET_LIBRARY'], sys.argv\n" + body
            + f"print('Notes with problems: {len(problem_notes)}')\nsys.exit(1 if {len(problem_notes)} else 0)\n",
            encoding="utf-8")

    def test_validate_problems_exit_3(self):
        # a problem in a note this run wrote fails the run (Windows separators, as the real validator prints them)
        self._fake_tools(["11_ASSET_LIBRARY\\Animation\\Camera\\ANIM-CAMERA-0001.md", "11_ASSET_LIBRARY\\Old.md"])
        self.clip(self.inbox / "camera", name="cam.mp4")
        code, doc = self.run_intake()
        self.assertEqual(code, 3, doc)
        v = doc["tools"]["validate"]
        self.assertEqual(doc["tools"]["build_mocs"]["exit"], 0)
        self.assertEqual((v["problems"], v["problems_this_run"], v["elsewhere"]), (2, 1, 1))
        self.assertFalse(v["ok"])
        self.assertIn("ANIM-CAMERA-0001.md", v["tail"])

    def test_validate_old_problems_elsewhere_dont_fail(self):
        # (critic) problems that were already in the vault made every run exit 3
        self._fake_tools(["11_ASSET_LIBRARY\\UI\\UI-REF-0001.md", "11_ASSET_LIBRARY/Breakdowns/Breakdown_X.md"])
        self.clip(self.inbox / "camera", name="cam.mp4")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        v = doc["tools"]["validate"]
        self.assertTrue(v["ok"])
        self.assertEqual((v["problems"], v["problems_this_run"], v["elsewhere"]), (2, 0, 2))

    # ---------------------------------------------------------------- critic round 1 regressions / new interface
    def test_numbers_brief_and_pack(self):
        self.clip(self.inbox / "combat", name="slam.mp4", note="combat: Slam")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        full = json.loads(Path(r["numbers"]).read_text(encoding="utf-8"))
        brief = json.loads(Path(r["numbers_brief"]).read_text(encoding="utf-8"))
        self.assertEqual(Path(r["numbers_brief"]).name, "numbers_brief.json")
        self.assertNotIn("energy", brief)
        self.assertNotIn("dx", brief["camera"])
        self.assertTrue(all("series" not in c for c in brief["regions"]["cells"]))
        self.assertEqual(brief["regions"]["lead_lag"], full["regions"]["lead_lag"])
        self.assertEqual([c["peak_frame"] for c in brief["regions"]["cells"]],
                         [c["peak_frame"] for c in full["regions"]["cells"]])
        for k in ("holds", "peaks", "hitstop_candidates", "slow_segments", "keypose_candidates", "timing_60"):
            self.assertEqual(brief[k], full[k], k)
        self.assertLess(len(Path(r["numbers_brief"]).read_bytes()), len(Path(r["numbers"]).read_bytes()))
        code, doc2 = self.run_intake("--pack", r["id"])
        self.assertEqual(code, 0, doc2)
        b = doc2["results"][0]
        for k in ("id", "kind", "category", "card", "breakdown", "media_dir", "numbers", "numbers_brief",
                  "user_note", "scale", "provenance"):
            self.assertEqual(b[k], r[k], k)
        self.assertEqual(sorted(b["sheets"]), sorted(r["sheets"]))
        self.assertTrue(1 <= len(b["frames"]) <= 6)
        for f in b["frames"]:
            self.assertTrue(Path(f).is_file())
            self.assertIn(int(Path(f).stem[2:]), full["keypose_candidates"])
        self.assertIn("spec", b)
        code, doc3 = self.run_intake("--pack", "ANIM-COMBAT-0099")
        self.assertEqual(code, 1)
        self.assertIn("ANIM-COMBAT-0099", doc3["error"])

    def test_overrides_and_set_meta(self):
        self.clip(self.inbox / "combat", name="hook.mp4", note="combat: Hook from a game I like")
        code, doc = self.run_intake("--provenance", "own", "--scale", "match")
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertEqual((r["provenance"], r["scale"]), ("own", "match"))
        card = Path(r["card"]).read_text(encoding="utf-8")
        self.assertIn("provenance: own", card)
        self.assertIn("scale: match", card)
        code, doc = self.run_intake("--set-meta", r["id"], "--provenance", "licensed", "--scale", "absolute")
        self.assertEqual(code, 0, doc)
        b = doc["results"][0]
        self.assertEqual((b["provenance"], b["scale"]), ("licensed", "absolute"))
        self.assertIn(r["card"], b["changed"])
        card = Path(r["card"]).read_text(encoding="utf-8")
        self.assertIn("provenance: licensed   # own | licensed | third-party", card)   # the comment stays
        self.assertIn("scale: absolute", card)
        self.assertIn("Provenance: `licensed`", card)
        self.assertIn("Scale: `absolute`", card)
        self.assertNotIn("`own`", card)
        self.assertIn("Scale: `absolute`", Path(r["breakdown"]).read_text(encoding="utf-8"))
        code, doc = self.run_intake("--set-meta", r["id"])
        self.assertEqual(code, 2)                                  # nothing to set
        code, doc = self.run_intake("--set-meta", "ANIM-COMBAT-0042", "--scale", "match")
        self.assertEqual(code, 1)

    def test_trim_from_note_and_flag(self):
        src = self.clip(self.inbox / "combat", name="long.mp4", note="combat: Jab\ntrim: 0.5-1.0", n=45)
        size = src.stat().st_size
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        nums = json.loads(Path(r["numbers"]).read_text(encoding="utf-8"))
        self.assertEqual(nums["trim"], [0.5, 1.0])
        self.assertEqual(r["trim"], [0.5, 1.0])
        self.assertAlmostEqual(nums["frames"], 15, delta=1)
        self.assertEqual((Path(r["media_dir"]) / "source" / "long.mp4").stat().st_size, size)   # source whole
        self.assertIn("trim 0.5–1 s", Path(r["card"]).read_text(encoding="utf-8"))
        src2 = self.clip(self.tmp / "out", name="other.mp4")
        code, doc = self.run_intake("--files", str(src2), "--category", "loco", "--trim", "0:00.2-0:00.6")
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["results"][0]["trim"], [0.2, 0.6])

    def test_bad_trim_fails_that_file_only(self):
        bad = self.clip(self.inbox / "combat", name="bad.mp4", note="combat: Bad\ntrim: 5-2")
        self.clip(self.inbox / "combat", name="good.mp4")
        code, doc = self.run_intake()
        self.assertEqual(code, 1, doc)
        e = next(x for x in doc["results"] if x["file"].endswith("bad.mp4"))
        self.assertEqual((e["kind"], e["code"]), ("error", "bad_trim"))
        self.assertTrue(bad.is_file())
        self.assertTrue(any(x.get("id") for x in doc["results"]))

    def test_clash_suffix_is_its_own_reference(self):
        self.clip(self.inbox / "combat", name="swing.mp4", note="combat\ntrim: 0.0-0.8")
        self.clip(self.inbox / "combat", name="swing-b.mp4", note="combat\ntrim: 0.7-1.5")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        res = [x for x in doc["results"] if x.get("id")]
        self.assertEqual(len(res), 2, doc["results"])               # not one pose set, two references
        self.assertEqual([x["title"] for x in res], ["Swing", "Swing"])
        self.assertEqual(sorted(x["trim"][0] for x in res), [0.0, 0.7])
        d = self.tmp / "names"
        d.mkdir()
        self.assertEqual(anim_intake.free_name(d, "a.mp4"), "a.mp4")
        (d / "a.mp4").write_bytes(b"")
        self.assertEqual(anim_intake.free_name(d, "a.mp4"), "a-b.mp4")
        (d / "a-b.mp4").write_bytes(b"")
        self.assertEqual(anim_intake.free_name(d, "a.mp4"), "a-c.mp4")

    def test_ctrl_c_rolls_back(self):
        src = self.clip(self.inbox / "combat", note="combat thing")
        before = snapshot(self.vault)
        with mock.patch.object(anim_intake, "_post_success_hook", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_intake()
        self.assertTrue(src.is_file())
        self.assertEqual(snapshot(self.vault), before)               # no half-made media, registry not bumped

    def test_nvdec_unsupported_is_per_file_not_exit_4(self):
        a = self.clip(self.inbox / "combat", name="a444.mp4")
        self.clip(self.inbox / "combat", name="b420.mp4")
        real = animlib.extract_frames

        def fake(src, *args, **kw):
            if Path(src).name == "a444.mp4" and kw.get("gpu"):
                raise animlib.NvdecUnsupported("nvdec_unsupported_format: h264 High 4:4:4 Predictive yuv444p ...")
            return real(src, *args, **kw)

        with mock.patch.object(animlib, "extract_frames", side_effect=fake):
            code, doc = self.run_intake(gpu="on")
        self.assertEqual(code, 1, doc)
        self.assertNotIn("error", doc)
        e = next(x for x in doc["results"] if x["file"].endswith("a444.mp4"))
        self.assertEqual((e["kind"], e["code"]), ("error", "nvdec_unsupported_format"))
        self.assertTrue(e["reason"].startswith("nvdec_unsupported_format"))
        self.assertTrue(a.is_file())
        self.assertTrue(any(x.get("id") for x in doc["results"]))

    def test_corrupt_file_fails_alone(self):
        # (critic) a corrupt mp4 was filed with made-up holds
        src = self.clip(self.inbox / "combat", name="broken.mp4", n=90)
        b = bytearray(src.read_bytes())
        rng = random.Random(3)
        for start in (int(len(b) * 0.45), int(len(b) * 0.6), int(len(b) * 0.75)):   # smash packets mid-file
            for i in range(start, start + 1500, 3):
                b[i] = rng.randrange(256)
        src.write_bytes(bytes(b))
        before = snapshot(self.vault)
        code, doc = self.run_intake()
        self.assertEqual(code, 1, doc)
        e = doc["results"][0]
        self.assertEqual((e["kind"], e["code"]), ("error", "decode_errors"), e)
        self.assertTrue(src.is_file())
        self.assertEqual(snapshot(self.vault), before)

    def test_dry_run_is_truthful(self):
        self.clip(self.inbox / "combat", name="fine.mp4")
        (self.inbox / "combat" / "garbage.mp4").write_bytes(bytes(range(256)) * 20)
        code, doc = self.run_intake("--dry-run")
        self.assertEqual(code, 0, doc)
        by = {Path(r["file"]).name: r for r in doc["results"]}
        self.assertTrue(by["fine.mp4"]["inbox_kept"])                 # nothing moves in a dry run
        self.assertFalse(by["fine.mp4"]["would_fail"])
        g = by["garbage.mp4"]
        self.assertTrue(g["would_fail"])
        self.assertEqual(g["code"], "probe_failed")
        self.assertIn("ffprobe failed", g["reason"])
        self.assertTrue(any("garbage.mp4" in w for w in doc["warnings"]))

    def test_summary_never_makes_wikilinks(self):
        # (critic) a one-item hold list printed as [[7, 18]] became a fake wikilink and failed validate
        nums = {"fps_analysis": 30, "frames": 40, "duration_s": 1.3, "fps_src": 30,
                "camera": {"moving": False, "path_range_px": 0, "shake_candidates": [[3, 5]]},
                "peaks": [12], "holds": [[7, 18]], "slow_segments": [[1, 6]], "hitstop_candidates": [[12, 13, 16]],
                "extremes": [], "smears": [], "cycle": None, "keypose_candidates": [1, 7, 18],
                "timing_60": {"peaks": [23], "holds": [[13, 35]], "slow_segments": [[1, 11]],
                              "hitstop_candidates": [[23, 25, 31]]},
                "decode_errors": {"events": 1, "lost_frames": 0, "suspect_frames": [20],
                                  "affected": {"holds": [[19, 22]]}},
                "notes": ["x [[y]] z"]}
        text = anim_intake.numbers_summary(nums, "gpu (cuda)")
        self.assertNotIn("[[", text)
        self.assertNotIn("]]", text)
        self.assertIn("7–18", text)
        self.assertIn("(12: 13–16)", text)

    def test_gif(self):
        fr = synth.square_clip(self.tmp / "gif frames", n=20)
        gif = self.inbox / "world" / "door.gif"
        gif.parent.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "20", "-i",
                        str(fr / "f_%04d.png"), str(gif)], check=True)
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertEqual((r["id"], r["kind"]), ("ANIM-WORLD-0001", "gif"))
        self.assertTrue(r["decode"].startswith("cpu"))
        nums = json.loads(Path(r["numbers"]).read_text(encoding="utf-8"))
        if GPU() == "on":
            self.assertTrue(any("no GPU decoder" in n for n in nums["notes"]))


class TestNoVideo(Base):
    def test_image_set_and_single(self):
        d = self.inbox / "ability"
        d.mkdir()
        for i in (1, 2, 3):
            Image.new("RGB", (300, 200), (40 * i, 80, 120)).save(d / f"pose_sheet_{i:02d}.png")
        (d / "pose_sheet.txt").write_text("Cast poses, licensed from mixamo", encoding="utf-8")
        Image.new("RGB", (200, 300), (200, 80, 20)).save(d / "single.jpg")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        res = sorted(doc["results"], key=lambda r: r["title"])
        self.assertEqual(len(res), 2, res)
        sheet_rec = next(r for r in res if r["title"] == "Pose sheet")
        self.assertEqual(sheet_rec["kind"], "images")
        self.assertEqual(sheet_rec["provenance"], "licensed")
        self.assertEqual(len(sheet_rec["sheets"]), 1)
        self.assertTrue(sheet_rec["sheets"][0].endswith("_contact.jpg"))
        mdir = Path(sheet_rec["media_dir"])
        # the three stills and (critic r2) their sidecar note
        self.assertEqual(sorted(p.name for p in (mdir / "source").iterdir()),
                         ["pose_sheet.txt", "pose_sheet_01.png", "pose_sheet_02.png", "pose_sheet_03.png"])
        self.assertEqual(len(list((mdir / "frames").iterdir())), 3)
        self.assertNotIn("{{", Path(sheet_rec["card"]).read_text(encoding="utf-8"))
        self.assertEqual(list(d.iterdir()), [])

    def test_skips_and_readme(self):
        (self.inbox / "rig.fbx").write_bytes(b"fbx")
        (self.inbox / "stray.txt").write_text("orphan", encoding="utf-8")
        (self.inbox / "notes.md").write_text("not a sidecar", encoding="utf-8")
        (self.inbox / "weird.xyz").write_bytes(b"?")
        code, doc = self.run_intake("--category", "combat")
        self.assertEqual(code, 0)
        by = {Path(r["file"]).name: r for r in doc["results"]}
        self.assertEqual(by["rig.fbx"]["reason"], "phase 4")
        self.assertEqual(by["stray.txt"]["reason"], "note without a reference file")
        self.assertIn("unsupported", by["weird.xyz"]["reason"])
        self.assertNotIn("README.md", by)
        self.assertNotIn("notes.md", by)
        self.assertEqual(doc["tools"], {})

    def test_roblox_catalog_missing(self):
        (self.inbox / "combat").mkdir()
        (self.inbox / "combat" / "pack.rbxm").write_bytes(b"<roblox!")
        with mock.patch.object(anim_intake, "load_catalog", return_value=None):
            code, doc = self.run_intake()
        self.assertEqual(code, 0)
        self.assertEqual(doc["results"][0]["reason"], "anim_catalog missing")
        self.assertTrue((self.inbox / "combat" / "pack.rbxm").is_file())

    def test_roblox_sequences(self):
        (self.inbox / "combat").mkdir()
        (self.inbox / "combat" / "pack.rbxm").write_bytes(b"<roblox!")
        (self.inbox / "combat" / "pack.rbxm.txt").write_text("Boxing set", encoding="utf-8")
        cat = fake_catalog(suspicious=["Script 'Loader': require(123)"])
        with mock.patch.object(anim_intake, "load_catalog", return_value=cat):
            code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        res = doc["results"]
        self.assertEqual([r["id"] for r in res], ["ANIM-COMBAT-0001", "ANIM-COMBAT-0002"])
        r = res[0]
        self.assertEqual((r["kind"], r["rig"]), ("roblox", "R15"))
        spec = json.loads(Path(r["spec"]).read_text(encoding="utf-8"))
        self.assertEqual(Path(r["spec"]).name, "ANIM-COMBAT-0001_v001.json")
        self.assertEqual((spec["source"], spec["provenance"], spec["id"]), ("data", "third-party", r["id"]))
        nums = json.loads(Path(r["numbers"]).read_text(encoding="utf-8"))
        self.assertEqual(nums["source"], "data")
        self.assertEqual(nums["keys"]["frames"], [1, 11, 13, 31])
        self.assertEqual(nums["frames"], 31)                              # (critic) the last key is frame 31
        self.assertEqual(nums["timing_60"]["frames"], 61)
        self.assertEqual(nums["markers"][0]["f"], 13)
        top = nums["speed_peaks"][0]
        self.assertEqual((top["part"], top["frames"]), ("RightUpperArm", [11, 13]))
        self.assertAlmostEqual(top["deg_s"], 120 / (2 / 30), delta=1)
        card = Path(r["card"]).read_text(encoding="utf-8")
        self.assertIn("WARNING, script scan", card)
        self.assertIn("require(123)", card)
        self.assertNotIn("{{", card)
        # a flagged pack is kept under a name Studio won't load, and the card says so
        self.assertFalse((Path(res[0]["media_dir"]) / "source" / "pack.rbxm").exists())
        self.assertTrue((Path(res[0]["media_dir"]) / "source" / "pack.rbxm.quarantine").is_file())
        self.assertEqual(r["quarantine"], "pack.rbxm.quarantine")
        self.assertIn("QUARANTINED", card)
        self.assertIn("source/pack.rbxm.quarantine", card)
        self.assertIn("QUARANTINED", (Path(res[1]["media_dir"]) / "source" / "SOURCE.txt").read_text(encoding="utf-8"))
        self.assertTrue(Path(r["numbers_brief"]).is_file())
        self.assertFalse((self.inbox / "combat" / "pack.rbxm").exists())
        # (critic r2) the sidecar is kept once, next to the stored source, and leaves the inbox
        self.assertEqual((Path(res[0]["media_dir"]) / "source" / "pack.rbxm.txt").read_text(encoding="utf-8"),
                         "Boxing set")
        self.assertFalse((self.inbox / "combat" / "pack.rbxm.txt").exists())

    def test_roblox_clean_scan_not_quarantined(self):
        (self.inbox / "combat").mkdir()
        (self.inbox / "combat" / "pack.rbxm").write_bytes(b"<roblox!")
        with mock.patch.object(anim_intake, "load_catalog", return_value=fake_catalog()):
            code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertIsNone(r["quarantine"])
        self.assertTrue((Path(r["media_dir"]) / "source" / "pack.rbxm").is_file())
        self.assertNotIn("QUARANTINED", Path(r["card"]).read_text(encoding="utf-8"))

    def test_roblox_with_real_catalog(self):
        """End to end with the real anim_catalog and its own test fixture, when both are present."""
        cat = anim_intake.load_catalog()
        fx = HERE / "test_anim_catalog.py"
        if cat is None or not fx.is_file():
            self.skipTest("anim_catalog or its fixture not present")
        spec = importlib.util.spec_from_file_location("t_anim_catalog", fx)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        (self.inbox / "combat").mkdir()
        (self.inbox / "combat" / "pack.rbxmx").write_text(mod.FIXTURE, encoding="utf-8")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertEqual(r["kind"], "roblox")
        self.assertTrue(r["scan"]["suspicious"])
        card = Path(r["card"]).read_text(encoding="utf-8")
        self.assertIn("WARNING, script scan", card)
        self.assertIn("Helper", card)
        self.assertNotIn("{{", card)
        nums = json.loads(Path(r["numbers"]).read_text(encoding="utf-8"))
        self.assertGreater(nums["keys"]["count"], 1)
        self.assertTrue(nums["markers"])
        sp = json.loads(Path(r["spec"]).read_text(encoding="utf-8"))
        self.assertEqual((sp["id"], sp["source"]), (r["id"], "data"))

    def test_bad_templates_exit_2(self):
        (self.vault / "_meta/templates/Template_Anim_Breakdown.md").write_text("no placeholders", encoding="utf-8")
        code, doc = self.run_intake("--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("Template_Anim_Breakdown.md", doc["error"])

    def test_bad_vault_exit_2(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = anim_intake.main(["--vault", str(self.tmp / "nowhere"), "--json"])
        self.assertEqual(code, 2)
        self.assertIn("11_ASSET_LIBRARY", json.loads(out.getvalue())["error"])

    def test_empty_inbox(self):
        code, doc = self.run_intake("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(doc["results"], [])
        self.assertEqual(doc["inbox"], [])

    def test_render_yaml_safety(self):
        t = anim_intake.render('---\na: "{{USER_NOTE}}"\nb: {{TITLE}}\n---\n> {{USER_NOTE}}\nx "{{USER_NOTE}}"\n',
                               {"USER_NOTE": 'line "one"\nline: two {{X}}', "TITLE": "Slam: big #1"})
        self.assertIn('a: "line \\"one\\"\\nline: two { {X} }"', t)
        self.assertIn('b: "Slam: big #1"', t)
        self.assertIn('> line "one"\n> line: two', t)
        self.assertIn('x "line "one" / line: two', t)
        self.assertNotIn("{{", t)


LINK_VALIDATOR = r'''import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINK = re.compile(r"\[\[([^\]|#^]+)")
DYN = re.compile(r"^(ANIM-[A-Z]+-\d{4}|Breakdown_.+)$")
names, paths = set(), []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in ("_media", "_inbox", "tools", "templates")]
    for f in fns:
        if f.endswith(".md"):
            names.add(f[:-3])
            paths.append(os.path.join(dp, f))
probs = {}
for p in paths:
    rel = os.path.relpath(p, ROOT)
    if not rel.startswith("11_ASSET_LIBRARY"):
        continue
    links = set(l.strip() for l in LINK.findall(open(p, encoding="utf-8").read()))
    links = set(l for l in links if not re.search(r"\.(png|jpe?g|gif|mp4|webp)$", l, re.I))
    bad = sorted(l for l in links if l not in names and not DYN.match(l))
    out = []
    if bad:
        out.append(f"UNREGISTERED links: {bad}")
    if os.path.basename(p).startswith("Category_"):
        out.append(f"only {len(links)} distinct links (<8)")
    if out:
        probs[rel] = out
for rel in sorted(probs):
    print(f"- {rel}")
    for x in probs[rel]:
        print(f"    {x}")
print(f"Notes with problems: {len(probs)}")
sys.exit(1 if probs else 0)
'''


class TestCriticRound2(Base):
    """(critic round 2) provenance from the note, pre-existing validate problems, peak-sync text, safe titles,
    the sidecar kept in source/, and the dry run's GPU check."""

    def image(self, folder, name="pose.png", note=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (120, 90), (90, 40, 160)).save(folder / name)
        if note is not None:
            (folder / (name + ".txt")).write_text(note, encoding="utf-8")
        return folder / name

    # ---------------------------------------------------------------- 1. provenance / scale
    PHRASINGS = [
        # (note, provenance, scale, guess)
        ("I want to match the snap of this punch, clip from a youtube video", "third-party", "absolute", "clear"),
        ("not mine, ripped from another game", "third-party", "absolute", "clear"),
        ("isn't mine", "third-party", "absolute", "clear"),
        ("I didn't make this, it's a reference", "third-party", "absolute", "clear"),
        ("from Jujutsu Shenanigans, the dash", "third-party", "absolute", "clear"),
        ("screen recording from tekken 8", "third-party", "absolute", "clear"),
        ("found it on tiktok", "third-party", "absolute", "clear"),
        ("match this exactly", "third-party", "absolute", "no_signal"),
        ("combat: heavy slam", "third-party", "absolute", "no_signal"),
        ("", "third-party", "absolute", "no_signal"),
        ("my own recording, match it exactly", "own", "match", "clear"),
        ("I recorded this myself", "own", "absolute", "clear"),
        ("I animated this in Blender, keep the timing 1:1", "own", "match", "clear"),
        ("this is mine", "own", "absolute", "clear"),
        ("combat: mine", "own", "absolute", "clear"),
        ("my animation from last week", "own", "absolute", "clear"),
        ("it's my clip, match it", "own", "match", "clear"),
        ("mixamo pack, match the timing", "licensed", "absolute", "clear"),
        ("bought on the asset store", "licensed", "absolute", "clear"),
        ("licensed from rokoko", "licensed", "absolute", "clear"),
        ("not licensed, from a streamer", "third-party", "absolute", "clear"),
        ("my own clip I found on tiktok", "third-party", "absolute", "ambiguous"),
        ("I recorded this from youtube", "third-party", "absolute", "ambiguous"),
        ("make it feel like mine", "third-party", "absolute", "ambiguous"),
        ("I animated this smash attack", "own", "absolute", "clear"),          # "smash" isn't a source
        ("my friends animation", "third-party", "absolute", "no_signal"),
    ]

    def test_provenance_table(self):
        for note, prov, scale, guess in self.PHRASINGS:
            with self.subTest(note=note):
                self.assertEqual(anim_intake.classify_note(note or None), (prov, scale, guess))
                self.assertEqual(anim_intake.provenance_of(note or None), prov)
                self.assertEqual(anim_intake.scale_of(note or None), scale)

    def test_provenance_flags_and_result_fields(self):
        opts = types.SimpleNamespace(provenance="own", scale=None)
        self.assertEqual(anim_intake.meta_of("match it 1:1", opts), ("own", "match", "override"))
        self.assertEqual(anim_intake.meta_of("from youtube", types.SimpleNamespace(provenance="licensed",
                                                                                   scale="match")),
                         ("licensed", "match", "override"))
        self.image(self.inbox / "combat", "yt.png", "combat: Jab\nmy own clip I found on tiktok, match it")
        self.image(self.inbox / "combat", "mine.png", "combat: Hook\nmy own recording, match it exactly")
        code, doc = self.run_intake("--dry-run")
        self.assertEqual(code, 0, doc)
        by = {Path(r["file"]).name: r for r in doc["results"]}
        self.assertEqual((by["yt.png"]["provenance"], by["yt.png"]["scale"], by["yt.png"]["provenance_guess"]),
                         ("third-party", "absolute", "ambiguous"))
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        by = {r["title"]: r for r in doc["results"]}
        self.assertEqual(by["Jab"]["provenance_guess"], "ambiguous")
        self.assertTrue(any("yt.png" in w and "unclear" in w for w in doc["warnings"]), doc["warnings"])
        self.assertEqual((by["Hook"]["provenance"], by["Hook"]["scale"], by["Hook"]["provenance_guess"]),
                         ("own", "match", "clear"))
        self.assertIn("provenance: third-party", Path(by["Jab"]["card"]).read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- 2. problems already in shared notes
    def _link_tools(self):
        tools = self.vault / "_meta/tools"
        tools.mkdir(parents=True, exist_ok=True)
        (tools / "build_mocs.py").write_text("print('mocs ok')\n", encoding="utf-8")
        (tools / "validate_vault.py").write_text(LINK_VALIDATOR, encoding="utf-8")
        # The real templates (copied when ANIMSMITH_VAULT is set) link notes this fake vault never registers,
        # so the link tests use the inline templates to count only the problems they plant.
        tpl = self.vault / "_meta" / "templates"
        for name, text in (("Template_Anim_Asset_Card.md", CARD), ("Template_Anim_Breakdown.md", BREAKDOWN)):
            (tpl / name).write_text(text, encoding="utf-8")

    def test_pre_existing_problem_in_index_doesnt_fail(self):
        # (critic r2 repro) an unregistered link on another plugin's index row made a filing exit 3
        self._link_tools()
        idx = self.lib / "Asset_Library_Index.md"
        idx.write_bytes(idx.read_bytes().replace(b"<!-- ASSET-ROWS:END -->",
                                                 b"| [[Some_Unwritten_Note]] | ui | other plugin | - | - | - | - "
                                                 b"| - |\r\n<!-- ASSET-ROWS:END -->"))
        self.image(self.inbox / "world", "door.png")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        v = doc["tools"]["validate"]
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["problems_this_run"], 0)
        self.assertGreaterEqual(v["elsewhere"], 2)            # the index and the World hub ("only N links")
        self.assertTrue(any("Asset_Library_Index.md" in x and "Some_Unwritten_Note" in x for x in v["pre_existing"]))
        self.assertTrue(any("only" in x for x in v["pre_existing"]))     # "only 1 links" -> "only 2 links": old

    def test_new_problem_in_shared_note_still_counts(self):
        self._link_tools()
        self.image(self.inbox / "world", "door.png")
        baseline = anim_intake.validate_baseline(anim_intake.Ctx(self.vault))
        self.assertNotIn("11_ASSET_LIBRARY/Asset_Library_Index.md", {k.replace("\\", "/") for k in baseline})
        # a row this run adds with a dangling link IS this run's problem
        with mock.patch.object(anim_intake, "add_index_row",
                               side_effect=lambda t, nl, row: anim_intake.INDEX_END.join(
                                   [t.split(anim_intake.INDEX_END)[0] + row + nl + "| [[Dangling_X]] |" + nl,
                                    t.split(anim_intake.INDEX_END)[1]])):
            code, doc = self.run_intake()
        self.assertEqual(code, 3, doc)
        v = doc["tools"]["validate"]
        self.assertEqual(v["problems_this_run"], 1)
        self.assertIn("Dangling_X", v["this_run"][0])

    def test_new_problems_diff(self):
        before = ["UNREGISTERED links: ['A']", "only 3 distinct links (<8)"]
        self.assertEqual(anim_intake.new_problems(["UNREGISTERED links: ['A', 'B']", "only 4 distinct links (<8)"],
                                                  before), ["UNREGISTERED links: ['B']"])
        self.assertEqual(anim_intake.new_problems(["UNREGISTERED links: ['A']"], before), [])
        self.assertEqual(anim_intake.new_problems(["missing roblox-dev tag"], before), ["missing roblox-dev tag"])
        self.assertEqual(anim_intake.new_problems(["x"], None), ["x"])

    # ---------------------------------------------------------------- 4. peak sync text
    def test_peak_sync_is_not_a_range(self):
        nums = {"fps_analysis": 30, "frames": 40, "duration_s": 1.3, "fps_src": 30, "camera": {},
                "audio": {"onsets": [{"ms": 1000}], "peak_sync": [{"peak": 32, "offset_frames": 1},
                                                                  {"peak": 12, "offset_frames": -2},
                                                                  {"peak": 7, "offset_frames": 0}]}}
        text = anim_intake.numbers_summary(nums)
        self.assertIn("32 (+1 f), 12 (−2 f), 7 (±0 f)", text)
        self.assertNotIn("32–1", text)

    # ---------------------------------------------------------------- 5. titles and the note
    def test_titles_are_plain_and_short(self):
        self.assertEqual(anim_intake.plain_title("a [[b]] | c # d"), "a b c d")
        t = anim_intake.plain_title("word " * 30)
        self.assertLessEqual(len(t), 60)
        self.assertFalse(t.endswith(" "))
        self.assertTrue(("word " * 30).startswith(t))                 # cut at a word boundary
        self.assertEqual(len(anim_intake.plain_title("x" * 90)), 60)   # one long word: hard cut
        note = ("combat: [[Evil]] | big # slam that keeps going far past the sixty character limit for titles ok\n"
                "the [[Hub]] link must not form | anywhere")
        self.image(self.inbox, "slam.png", note)
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        r = doc["results"][0]
        self.assertLessEqual(len(r["title"]), 60)
        for bad in ("[[", "]]", "|", "#"):
            self.assertNotIn(bad, r["title"])
        self.assertEqual(r["user_note"], note)                         # the JSON keeps the note verbatim
        card = Path(r["card"]).read_text(encoding="utf-8")
        h1 = next(l for l in card.splitlines() if l.startswith("# "))
        self.assertEqual(h1, f"# {r['id']} — {r['title']}")
        self.assertNotIn("[[Evil]]", card)
        self.assertNotIn("[[Hub]]", card)
        self.assertIn("⟦Evil⟧", card)
        hub = (self.lib / f"{animlib.CATEGORIES['combat']['hub']}.md").read_text(encoding="utf-8")
        line = next(l for l in hub.splitlines() if r["id"] in l)
        self.assertEqual(line.count("[["), 1)
        self.assertNotIn("#", line)
        idx = (self.lib / "Asset_Library_Index.md").read_text(encoding="utf-8")
        row = next(l for l in idx.splitlines() if r["id"] in l)
        self.assertEqual(row.count("|"), 9)                             # 8 cells, none split
        self.assertEqual(row.count("[["), 1)

    # ---------------------------------------------------------------- 7. the sidecar moves into source/
    def test_sidecar_copied_into_source(self):
        self.image(self.inbox / "camera", "pan.png", "camera: Pan\nlovely")
        code, doc = self.run_intake()
        self.assertEqual(code, 0, doc)
        src = Path(doc["results"][0]["media_dir"]) / "source"
        self.assertEqual(sorted(p.name for p in src.iterdir()), ["pan.png", "pan.png.txt"])
        self.assertEqual((src / "pan.png.txt").read_text(encoding="utf-8"), "camera: Pan\nlovely")
        self.assertEqual(list((self.inbox / "camera").iterdir()), [])
        # outside the inbox: copied, the user's files stay
        p = self.image(self.tmp / "else where", "x.png", "a note")
        code, doc = self.run_intake("--files", str(p), "--category", "world")
        self.assertEqual(code, 0, doc)
        self.assertTrue((Path(doc["results"][0]["media_dir"]) / "source" / "x.png.txt").is_file())
        self.assertTrue((self.tmp / "else where" / "x.png.txt").is_file())

    # ---------------------------------------------------------------- 6. the dry run checks the GPU
    def test_dry_run_gpu_not_checked_without_video(self):
        self.image(self.inbox / "combat", "a.png")
        with mock.patch.object(animlib, "gpu_check") as gc:
            code, doc = self.run_intake("--dry-run", gpu="on")
        self.assertEqual(code, 0, doc)
        gc.assert_not_called()
        self.assertIsNone(doc["gpu_ok"])
        self.assertIn("not checked", doc["gpu_reason"])

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
    def test_dry_run_predicts_gpu_failure(self):
        self.clip(self.inbox / "combat", name="a.mp4")
        self.clip(self.inbox / "combat", name="b.mp4")
        err = animlib.GpuError("gpu_failed: ffmpeg -hwaccel cuda did not start (test)")
        with mock.patch.object(animlib, "gpu_check", side_effect=err) as gc:
            code, doc = self.run_intake("--dry-run", gpu="on")
        self.assertEqual(code, 0, doc)
        self.assertEqual(gc.call_count, 1)                              # once per run, not per file
        self.assertIs(doc["gpu_ok"], False)
        self.assertIn("gpu_failed", doc["gpu_reason"])
        for r in doc["results"]:
            self.assertTrue(r["would_fail"])
            self.assertEqual(r["code"], "gpu_failed")
        self.assertTrue(any("exit 4" in w for w in doc["warnings"]))
        with mock.patch.object(animlib, "gpu_check", return_value=None) as gc:
            code, doc = self.run_intake("--dry-run", gpu="on")
        self.assertEqual(gc.call_count, 1)
        self.assertIs(doc["gpu_ok"], True)
        self.assertFalse(any(r["would_fail"] for r in doc["results"]))
        with mock.patch.object(animlib, "gpu_check") as gc:
            code, doc = self.run_intake("--dry-run", gpu="off")
        gc.assert_not_called()
        self.assertIsNone(doc["gpu_ok"])


if __name__ == "__main__":
    unittest.main()
