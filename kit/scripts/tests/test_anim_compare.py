import io
import json
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anim_compare as C  # noqa: E402


def make_clip(folder, still_in, move, still_out, size=64):
    """A square that is still, then sweeps with ease-in/out, then is still again. One png per frame."""
    os.makedirs(folder, exist_ok=True)
    n = still_in + move + still_out
    for i in range(n):
        t = min(max((i - still_in) / max(move - 1, 1), 0.0), 1.0)
        x = int(4 + t * t * (3 - 2 * t) * 36)
        im = Image.new("RGB", (size, size), (20, 20, 20))
        ImageDraw.Draw(im).rectangle([x, 20, x + 14, 40], fill=(230, 230, 230))
        im.save(os.path.join(folder, f"f_{i + 1:04d}.png"))
    return n


class Dtw(unittest.TestCase):
    def test_vectorised_matches_reference(self):
        rng = random.Random(3)
        for n, m in ((1, 1), (2, 5), (17, 17), (30, 41), (55, 23)):
            x = [rng.random() for _ in range(n)]
            y = [rng.random() for _ in range(m)]
            self.assertEqual(C.dtw(x, y), C.dtw_reference(x, y), (n, m))

    def test_synthetic_energy_curves(self):
        ref = np.sin(np.pi * np.linspace(0, 1, 40)) ** 2
        cap = np.sin(np.pi * np.linspace(0, 1, 60)) ** 2
        p = C.dtw(ref, cap)
        self.assertEqual(p[0], (0, 0))
        self.assertEqual(p[-1], (39, 59))
        self.assertEqual(p, C.dtw_reference(ref, cap))


class Trim(unittest.TestCase):
    def test_parse_trim(self):
        self.assertEqual(C.parse_trim("5,20", 30), (5, 20))
        self.assertEqual(C.parse_trim("20,5", 30), (5, 20))
        self.assertEqual(C.parse_trim("0,99", 30), (1, 30))
        with self.assertRaises(SystemExit):
            C.parse_trim("a,b", 30)
        with self.assertRaises(SystemExit):
            C.parse_trim("7,7", 30)

    def test_trim_overrides_automatic_range(self):
        with tempfile.TemporaryDirectory(prefix="cmp dir ") as d:
            ref, cap = os.path.join(d, "ref"), os.path.join(d, "cap")
            make_clip(ref, 4, 20, 4)
            make_clip(cap, 12, 20, 12)
            auto, _, _ = C.compare(ref, cap, 60.0)
            trimmed, _, _ = C.compare(ref, cap, 60.0, trim="10,34")
            self.assertEqual(trimmed["cap_active"], [10, 34])
            self.assertNotEqual(auto["cap_active"], [10, 34])
            # the automatic trim drops the still lead-in/out, so the durations roughly agree
            self.assertLess(abs(auto["duration_ratio"] - 1.0), 0.35)
            self.assertGreater(auto["score"], 40)

    def test_main_cli_with_trim_and_log(self):
        with tempfile.TemporaryDirectory(prefix="cmp cli ") as d:
            ref, cap = os.path.join(d, "ref"), os.path.join(d, "cap")
            make_clip(ref, 3, 18, 3)
            make_clip(cap, 5, 18, 5)
            self.assertEqual(C.main([ref, cap, "--fps", "60", "--trim", "4,26"]), 0)
            log = json.load(open(os.path.join(ref, "iterations.json")))
            self.assertEqual(log[0]["cap_active"], [4, 26])
            self.assertTrue(os.path.exists(os.path.join(ref, "compare_iter001.png")))


class Decode(unittest.TestCase):
    """(critic B1) the capture decode goes through animlib.extract_frames: never a silent CPU decode."""

    def test_extract_uses_animlib_with_exact_fps(self):
        import animlib
        with tempfile.TemporaryDirectory(prefix="cmp dec ") as d:
            with mock.patch.object(animlib, "extract_frames", return_value={"notes": []}) as ef:
                C.extract(os.path.join(d, "cap.mp4"), os.path.join(d, "out"), 60.0, gpu=True)
            args, kw = ef.call_args
            self.assertEqual((kw["fps_exact"], kw["gpu"]), (60.0, True))

    def test_exit_codes(self):
        import animlib
        with tempfile.TemporaryDirectory(prefix="cmp dec ") as d:
            ref = os.path.join(d, "ref")
            make_clip(ref, 3, 10, 3)
            cap = os.path.join(d, "cap.mp4")
            open(cap, "wb").write(b"x")
            for exc, code in ((animlib.GpuError("gpu_failed: x"), 4),
                              (animlib.NvdecUnsupported("nvdec_unsupported_format: h264 yuv444p"), 5),
                              (animlib.DecodeError("decode_errors: corrupt"), 1)):
                with mock.patch.object(animlib, "extract_frames", side_effect=exc), \
                        redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
                    self.assertEqual(C.main([ref, cap, "--fps", "60"]), code)
                self.assertIn(exc.code, err.getvalue())


class Media(unittest.TestCase):
    def test_resolve_media_prefers_new_then_legacy(self):
        with tempfile.TemporaryDirectory(prefix="my vault ") as v:
            lib = os.path.join(v, "11_ASSET_LIBRARY", "_media")
            legacy = os.path.join(lib, "frames", "ANIM-X-0001")
            make_clip(legacy, 1, 4, 1)
            root, frames = C.resolve_media(v, "ANIM-X-0001")
            self.assertEqual(os.path.normpath(frames), os.path.normpath(legacy))
            new = os.path.join(lib, "anim", "ANIM-X-0001", "frames")
            make_clip(new, 1, 4, 1)
            root, frames = C.resolve_media(v, "ANIM-X-0001")
            self.assertEqual(os.path.normpath(frames), os.path.normpath(new))
            self.assertEqual(os.path.normpath(root), os.path.normpath(os.path.dirname(new)))


if __name__ == "__main__":
    unittest.main()
