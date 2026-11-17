"""Tests for animlib.py: vault resolution, categories, the ID registry and its lock, ffmpeg helpers (GPU rule) and
sheets. Temp folders with spaces in their paths, synthetic media only.

    python -m unittest discover -s kit/scripts/tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import animlib  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def lavfi(out, spec, extra=()):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", spec, *extra,
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="anim lib "))
        self.vault = self.tmp / "my vault"
        (self.vault / "11_ASSET_LIBRARY").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestVault(Base):
    def test_resolve_arg_env_and_errors(self):
        self.assertEqual(animlib.resolve_vault(str(self.vault)), self.vault.resolve())
        with mock.patch.dict(os.environ, {"ANIMSMITH_VAULT": f' "{self.vault}" '}):
            self.assertEqual(animlib.resolve_vault(None), self.vault.resolve())
        with mock.patch.dict(os.environ, {"ANIMSMITH_VAULT": ""}):
            with self.assertRaises(SystemExit) as cm:
                animlib.resolve_vault(None)
            self.assertIn("ANIMSMITH_VAULT", str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            animlib.resolve_vault(str(self.tmp))
        self.assertIn("11_ASSET_LIBRARY", str(cm.exception))
        self.assertEqual(animlib.lib(self.vault), self.vault / "11_ASSET_LIBRARY")

    def test_categories(self):
        self.assertEqual(set(animlib.CATEGORIES),
                         {"combat", "weapon", "ability", "loco", "world", "camera", "reaction"})
        self.assertEqual(animlib.CATEGORIES["loco"]["folder"], "Animation/Locomotion")
        self.assertEqual(animlib.CATEGORIES["reaction"]["prefix"], "ANIM-REACTION")
        self.assertEqual(animlib.CATEGORIES["camera"]["hub"], "Category_Camera_Animation")
        for meta in animlib.CATEGORIES.values():
            self.assertTrue(meta["tag"].startswith("asset/"))
        self.assertEqual(animlib.category_of("Locomotion:"), "loco")
        self.assertEqual(animlib.category_of("COMBAT"), "combat")
        self.assertIsNone(animlib.category_of("banana"))


class TestIds(Base):
    def test_next_id_from_disk_and_registry(self):
        lib = self.vault / "11_ASSET_LIBRARY"
        self.assertEqual(animlib.next_id(self.vault, "combat"), "ANIM-COMBAT-0001")
        (lib / "_media").mkdir()
        (lib / "_media" / "ANIM-LOCO-0014_contact_sheet.png").write_bytes(b"x")
        (lib / "Animation" / "_specs" / "ANIM-LOCO-0015").mkdir(parents=True)
        self.assertEqual(animlib.next_id(self.vault, "loco"), "ANIM-LOCO-0016")
        animlib.write_json(lib / "Animation" / "_ids.json", {"ANIM-LOCO": 20, "ANIM-COMBAT": 3})
        self.assertEqual(animlib.next_id(self.vault, "loco"), "ANIM-LOCO-0021")
        self.assertEqual(animlib.next_id(self.vault, "combat", skip=1), "ANIM-COMBAT-0005")

    def test_claim_lock_and_registry(self):
        lib = self.vault / "11_ASSET_LIBRARY"
        reg = lib / "Animation" / "_ids.json"
        reg.parent.mkdir(parents=True)
        reg.write_bytes(b'{\r\n "ANIM-WEAPON": 0,\r\n "ANIM-COMBAT": 0\r\n}\r\n')
        mdir = animlib.claim_id(self.vault, "ANIM-COMBAT-0001")
        self.assertTrue(mdir.is_dir())
        self.assertEqual(mdir, lib / "_media" / "anim" / "ANIM-COMBAT-0001")
        raw = reg.read_bytes()
        self.assertIn(b"\r\n", raw)                                  # line endings kept
        self.assertEqual(list(json.loads(raw)), ["ANIM-WEAPON", "ANIM-COMBAT"])   # key order kept
        self.assertEqual(json.loads(raw)["ANIM-COMBAT"], 1)
        with self.assertRaises(FileExistsError):
            animlib.claim_id(self.vault, "ANIM-COMBAT-0001")
        shutil.rmtree(mdir)                                          # media deleted by hand ...
        self.assertEqual(animlib.next_id(self.vault, "combat"), "ANIM-COMBAT-0002")   # ... id still not reused


class TestCriticRound1(Base):
    def test_id_scan_skips_media_contents(self):
        # (critic B12) a claim must not walk every frame JPEG; a name inside a media folder is not an ID claim
        lib = self.vault / "11_ASSET_LIBRARY"
        fr = lib / "_media" / "anim" / "ANIM-COMBAT-0007" / "frames"
        fr.mkdir(parents=True)
        (fr / "ANIM-COMBAT-0099_f.jpg").write_bytes(b"x")
        (lib / "Breakdowns").mkdir()
        (lib / "Breakdowns" / "Breakdown_ANIM-COMBAT-0008.md").write_text("x", encoding="utf-8")
        seen = []
        real = os.walk

        def spy(top, *a, **k):
            for dp, dn, fn in real(top, *a, **k):
                seen.append(Path(dp).name)
                yield dp, dn, fn

        with mock.patch.object(animlib.os, "walk", side_effect=spy):
            self.assertEqual(animlib.next_id(self.vault, "combat"), "ANIM-COMBAT-0009")
        self.assertNotIn("frames", seen)
        self.assertNotIn("ANIM-COMBAT-0007", seen)

    def test_pillow_is_lazy(self):
        # (critic B10) anim_find is stdlib-only; importing animlib must not need Pillow
        code = ("import sys; sys.modules['PIL'] = None; sys.path.insert(0, sys.argv[1]); import animlib, anim_find; "
                "print(animlib.next_id.__name__, anim_find.main.__name__)")
        r = subprocess.run([sys.executable, "-c", code, str(HERE.parent)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("next_id main", r.stdout)
        self.assertIs(animlib.Image, __import__("PIL.Image", fromlist=["Image"]))

    def test_parse_trim(self):
        self.assertEqual(animlib.parse_trim("2.0-5.0"), [2.0, 5.0])
        self.assertEqual(animlib.parse_trim(" 2 - 5.5s "), [2.0, 5.5])
        self.assertEqual(animlib.parse_trim("0:02-0:05.25"), [2.0, 5.25])
        self.assertEqual(animlib.parse_trim("1.5\u20133"), [1.5, 3.0])
        for bad in ("5-2", "abc", "2", "-1-3"):
            with self.assertRaises(animlib.BadTrim):
                animlib.parse_trim(bad)

    def test_scan_decode_log(self):
        log = "\n".join([
            "[Parsed_showinfo_0 @ 0000] n:   0 pts:      0 pts_time:0       pos: 48",
            "[Parsed_showinfo_0 @ 0000] n:   1 pts:    256 pts_time:0.0333333 pos: 99",
            "[h264 @ 0000] Invalid NAL unit size (42504 > 254).",
            "[h264 @ 0000] Error splitting the input into NAL units.",
            "Error while decoding stream #0:0: Invalid data found when processing input",
            "[Parsed_showinfo_0 @ 0000] n:   2 pts:   1024 pts_time:0.133333 pos: 400",
            "[Parsed_showinfo_0 @ 0000] n:   3 pts:   1280 pts_time:0.166667 pos: 450",
        ])
        r = animlib.scan_decode_log(log, 30, 30, 6)
        self.assertEqual((r["events"], r["lost_frames"]), (1, 2))       # 0.0333 -> 0.1333: 2 frames dropped
        self.assertEqual(r["suspect_frames"], [3, 4, 5])
        self.assertEqual(animlib.scan_decode_log(log.replace("Error while", "fine"), 30, 30, 6)["events"], 0)

    def _fake_run(self, stderr, rc=0):
        def run(cmd):
            out = Path(cmd[-1]).parent if str(cmd[-1]).endswith(".jpg") else None
            if out is not None and rc == 0:
                Image.new("RGB", (32, 32)).save(out / "f_0001.jpg")      # what ffmpeg's CPU fallback leaves
            return subprocess.CompletedProcess(cmd, rc, "", stderr)
        return run

    def test_gpu_error_classes(self):
        # (critic B2) not every ffmpeg failure is gpu_failed
        info = {"width": 64, "height": 64, "fps": 30.0, "duration": 1.0, "nb_frames": 30, "codec": "h264",
                "pix_fmt": "yuv420p", "profile": "High", "has_audio": False}
        out = self.tmp / "fr"
        cases = [
            ("[h264 @ 1] Hardware is lacking required capabilities\n[h264 @ 1] Failed setup for format cuda: "
             "hwaccel initialisation returned error.", 0, None, animlib.NvdecUnsupported),
            ("[h264 @ 1] Failed setup for format cuda: hwaccel initialisation returned error.", 0, True,
             animlib.NvdecUnsupported),
            ("[h264 @ 1] Failed setup for format cuda: hwaccel initialisation returned error.", 0, False,
             animlib.GpuError),
            ("Device creation failed: -542398533.", 1, None, animlib.GpuError),
            ("[NULL @ 1] Unable to parse option value: moov atom not found", 1, None, animlib.AnimError),
        ]
        for stderr, rc, sane, exc in cases:
            with self.subTest(stderr=stderr[:40]), mock.patch.object(animlib, "probe", return_value=dict(info)), \
                    mock.patch.object(animlib, "_run", side_effect=self._fake_run(stderr, rc)), \
                    mock.patch.object(animlib, "gpu_sanity", return_value=bool(sane)):
                with self.assertRaises(exc) as cm:
                    animlib.extract_frames(self.tmp / "x.mp4", out, gpu=True)
                self.assertIs(type(cm.exception), exc)
                self.assertTrue(str(cm.exception).startswith(cm.exception.code + ":") or exc is animlib.AnimError)
                self.assertEqual(list(out.glob("f_*.jpg")), [])          # CPU-fallback frames thrown away
        # a format NVDEC can't take is refused before any decode
        with mock.patch.object(animlib, "probe", return_value=dict(info, pix_fmt="yuv444p",
                                                                    profile="High 4:4:4 Predictive")), \
                mock.patch.object(animlib, "_run", side_effect=AssertionError("must not decode")):
            with self.assertRaises(animlib.NvdecUnsupported) as cm:
                animlib.extract_frames(self.tmp / "x.mp4", out, gpu=True)
        self.assertIn("4:4:4", str(cm.exception))
        self.assertEqual(animlib.error_code(cm.exception), "nvdec_unsupported_format")
        self.assertEqual(animlib.error_code(ValueError("x")), "error")


class TestSheet(Base):
    def test_sheet_labels_and_inputs(self):
        a = self.tmp / "a.png"
        Image.new("RGB", (200, 100), (200, 20, 20)).save(a)
        b = Image.new("RGB", (200, 100), (20, 200, 20))
        out = animlib.sheet([(a, "f1"), (b, "f2"), a], self.tmp / "out dir" / "s.jpg", cols=2, title="T")
        with Image.open(out) as im:
            self.assertEqual(im.size[0], 400)
            self.assertEqual(im.format, "JPEG")
        with self.assertRaises(ValueError):
            animlib.sheet([], self.tmp / "x.png")
        self.assertIsNotNone(animlib.font(12))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
class TestFfmpeg(Base):
    def test_probe_and_audio_flag(self):
        v = lavfi(self.tmp / "v.mp4", "testsrc=size=320x180:rate=24:duration=1")
        p = animlib.probe(v)
        self.assertEqual((p["width"], p["height"], p["codec"], p["has_audio"]), (320, 180, "h264", False))
        self.assertAlmostEqual(p["fps"], 24, delta=0.01)
        with self.assertRaises(RuntimeError):
            animlib.probe(self.tmp / "missing.mp4")

    def test_extract_cap_width_frames_cpu(self):
        v = lavfi(self.tmp / "fast clip.mp4", "testsrc=size=960x540:rate=120:duration=1")
        ex = animlib.extract_frames(v, self.tmp / "fr", gpu=False, max_frames=40)
        self.assertEqual(ex["fps"], 60)                      # capped at 60
        self.assertEqual(ex["frames"], 40)                   # capped at max_frames
        self.assertTrue(ex["truncated"])
        self.assertEqual(ex["width"], 480)
        self.assertTrue(Path(ex["files"][0]).name == "f_0001.jpg")
        self.assertEqual(ex["decode"], "cpu (--gpu off)")
        small = lavfi(self.tmp / "small.mp4", "testsrc=size=320x180:rate=30:duration=1")
        ex = animlib.extract_frames(small, self.tmp / "fr2", gpu=False, crop=[0, 0, 160, 90])
        self.assertEqual((ex["width"], ex["frames"], ex["fps"]), (160, 30, 30))   # never upscaled

    def test_bad_crop_and_trim_are_not_gpu_failures(self):
        v = lavfi(self.tmp / "v.mp4", "testsrc=size=320x180:rate=30:duration=2")
        with self.assertRaises(animlib.BadCrop) as cm:
            animlib.extract_frames(v, self.tmp / "fr", gpu=True, crop=[300, 0, 100, 100])
        self.assertTrue(str(cm.exception).startswith("bad_crop"))
        with self.assertRaises(animlib.BadTrim):
            animlib.extract_frames(v, self.tmp / "fr", gpu=True, trim=[5.0, 6.0])
        ex = animlib.extract_frames(v, self.tmp / "fr2", gpu=False, trim=[0.5, 1.0])
        self.assertEqual(ex["trim"], [0.5, 1.0])
        self.assertAlmostEqual(ex["frames"], 15, delta=1)
        with self.assertRaises(animlib.ProbeError) as cm:
            animlib.probe(self.tmp / "missing.mp4")
        self.assertEqual(cm.exception.code, "probe_failed")

    def test_corrupt_clip_fails_with_decode_errors(self):
        # (critic B6) a corrupt mp4 was decoded "fine" and filed with fake holds
        v = lavfi(self.tmp / "v.mp4", "testsrc=size=320x180:rate=30:duration=3", ("-c:v", "mpeg4", "-q:v", "3"))
        b = bytearray(v.read_bytes())
        for start in (int(len(b) * 0.4), int(len(b) * 0.6), int(len(b) * 0.8)):
            for i in range(start, start + 1200, 3):
                b[i] ^= 0xA5
        v.write_bytes(bytes(b))
        with self.assertRaises(animlib.DecodeError) as cm:
            animlib.extract_frames(v, self.tmp / "fr", gpu=False)
        self.assertTrue(str(cm.exception).startswith("decode_errors"))
        self.assertEqual(list((self.tmp / "fr").glob("f_*.jpg")), [])

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
    def test_real_444_clip_is_nvdec_unsupported(self):
        v = self.tmp / "v444.mp4"
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=size=256x192:rate=30:duration=1", "-c:v", "h264_nvenc", "-profile:v", "high444p",
                            "-pix_fmt", "yuv444p", str(v)], capture_output=True)
        if r.returncode != 0:
            self.skipTest("no h264_nvenc 4:4:4 encoder here")
        with self.assertRaises(animlib.NvdecUnsupported):
            animlib.extract_frames(v, self.tmp / "fr", gpu=True)
        ex = animlib.extract_frames(v, self.tmp / "fr", gpu=False)       # only when the user said so
        self.assertEqual(ex["decode"], "cpu (--gpu off)")

    def test_gpu_failure_raises(self):
        v = lavfi(self.tmp / "v.mp4", "testsrc=size=320x180:rate=30:duration=1")
        with mock.patch.dict(os.environ, {"ANIMSMITH_HWACCEL": "not_a_real_accel"}):
            with self.assertRaises(animlib.GpuError) as cm:
                animlib.extract_frames(v, self.tmp / "fr", gpu=True)
            self.assertTrue(str(cm.exception).startswith("gpu_failed"))
            self.assertEqual(list((self.tmp / "fr").glob("f_*.jpg")), [])
            with self.assertRaises(animlib.GpuError):
                animlib.gpu_check(True)
            animlib.gpu_check(False)                         # --gpu off: nothing to check
            ex = animlib.extract_frames(v, self.tmp / "fr", gpu=False)
        self.assertEqual(ex["frames"], 30)


if __name__ == "__main__":
    unittest.main()
