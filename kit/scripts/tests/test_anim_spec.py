import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anim_rig as R  # noqa: E402
import anim_spec as A  # noqa: E402

SCRIPT = str(Path(__file__).resolve().parents[1] / "anim_spec.py")


def good_spec():
    def key(f, r, e="CubicV2", d="InOut", p=None):
        k = {"f": f, "r": r, "e": e, "d": d}
        if p:
            k["p"] = p
        return k
    return {
        "id": "ANIM-TEST-0001", "version": 1, "name": "test", "rig": "R15", "space": "rel", "fps": 60, "length": 30,
        "loop": False, "priority": "Action", "category": "loco", "markers": [{"name": "Mid", "f": 15}],
        "tracks": {
            "LowerTorso": [key(0, [0, 0, 0]), key(15, [0, 10, 0], p=[0, 0.1, 0]), key(30, [0, 0, 0])],
            "UpperTorso": [key(0, [0, 0, 0]), key(17, [-8, 25, 0]), key(30, [0, 0, 0])],
            "RightUpperArm": [key(0, [0, 0, 0]), key(18, [70, 20, 30], "CubicV2", "Out"), key(30, [10, 0, 0])],
            "LeftUpperArm": [key(0, [0, 0, 0]), key(20, [-30, 10, -20]), key(30, [0, 0, 0])],
            "Head": [key(0, [0, 0, 0]), key(19, [-5, -15, 0]), key(30, [0, 0, 0])],
        },
        "history": [],
    }


def with_sword(s):
    s["extra_joints"] = {"Sword": {"parent": "RightHand"}}
    s["tracks"]["Sword"] = [{"f": 0, "r": [0, 0, 0]}, {"f": 30, "r": [20, 0, 0]}]
    return s


class RoundTrip(unittest.TestCase):
    def test_rel_joint_rel(self):
        rng = random.Random(7)
        for rigname in ("R6", "R15"):
            rig = R.load_rig(rigname)
            for part in rig["parts"]:
                for _ in range(5):
                    rel = R.euler_to_mat([rng.uniform(-80, 80) for _ in range(3)])
                    off = [rng.uniform(-1, 1) for _ in range(3)]
                    jr, jp = R.rel_to_joint(rig, part, rel, off)
                    back, boff = R.joint_to_rel(rig, part, jr, jp)
                    self.assertLess(R.angle_between(rel, back), 1e-4, (rigname, part))
                    for a, b in zip(off, boff):
                        self.assertAlmostEqual(a, b, places=9)

    def test_euler_round_trip(self):
        for e in ([10, 20, 30], [-45, 5, 60], [0, 0, 0]):
            for a, b in zip(R.mat_to_euler(R.euler_to_mat(e)), e):
                self.assertAlmostEqual(a, b, places=3)


class Lint(unittest.TestCase):
    def test_clean_spec_has_no_errors(self):
        res = A.lint(good_spec())
        self.assertFalse([m for lvl, m in res if lvl == "error"], res)
        self.assertTrue(any(m.startswith("schema: ok") for _, m in res))

    def test_bad_part_name_is_schema_error(self):
        s = good_spec()
        s["tracks"]["RightArmm"] = [{"f": 0, "r": [0, 0, 0]}]
        res = A.lint(s)
        self.assertEqual(res[0][0], "error")
        self.assertIn("RightArmm", res[0][1])
        self.assertTrue(all(lvl == "error" for lvl, _ in res))  # heuristics do not run on a malformed spec

    def test_schema_catches_style_direction_range_marker(self):
        s = good_spec()
        s["tracks"]["Head"][1]["e"] = "Wobble"
        s["tracks"]["Head"][1]["d"] = "Sideways"
        s["tracks"]["UpperTorso"][1]["f"] = 99
        s["tracks"]["LowerTorso"][0]["r"] = [1, 2]
        s["markers"] = [{"name": "Bad", "f": "x"}, {"name": "Late", "f": 500}]
        text = "\n".join(A.schema_check(s))
        for needle in ("Wobble", "Sideways", "outside 0..30", "three numbers", "marker 'Bad'", "marker 'Late'"):
            self.assertIn(needle, text)

    def test_extra_joint_part_is_allowed(self):
        s = with_sword(good_spec())
        self.assertEqual(A.schema_check(s), [])
        s["extra_joints"]["Sword"]["parent"] = "NoSuchPart"
        self.assertTrue(any("NoSuchPart" in e for e in A.schema_check(s)))


class Build(unittest.TestCase):
    def test_luau_finds_motor6d_and_animationconstraint(self):
        s = with_sword(good_spec())
        rig = A.rig_of(s)
        text = A.emit_luau(s, A.keyframe_table(s, rig), rig)
        self.assertIn("AnimationConstraint", text)
        self.assertIn("Motor6D", text)
        self.assertNotIn(".C0", text)
        self.assertNotIn(".C1", text)
        self.assertIn('findJoint(rig, "Sword")', text)
        pose = A.emit_pose_luau(s, rig, 15)
        self.assertIn("AnimationConstraint", pose)
        self.assertNotIn("C0 =", pose)

    def test_cli_build_refuses_broken_spec(self):
        with tempfile.TemporaryDirectory(prefix="anim spec ") as d:
            s = good_spec()
            s["tracks"]["Nope"] = [{"f": 0, "r": [0, 0, 0]}]
            sp = os.path.join(d, "bad.json")
            json.dump(s, open(sp, "w"))
            out = os.path.join(d, "out.luau")
            r = subprocess.run([sys.executable, SCRIPT, "build", sp, "--luau", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertFalse(os.path.exists(out))
            json.dump(good_spec(), open(sp, "w"))
            r = subprocess.run([sys.executable, SCRIPT, "build", sp, "--luau", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(os.path.exists(out))

    def test_preview_skips_extra_joint_parts(self):
        import anim_preview as P
        b = P.bake(with_sword(good_spec()), 30)
        self.assertEqual(b["skippedParts"], ["Sword"])
        self.assertEqual(len(b["frames"]), 16)


if __name__ == "__main__":
    unittest.main()
