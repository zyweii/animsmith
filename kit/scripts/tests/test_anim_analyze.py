"""Tests for anim_analyze.py (v2) on synthetic frames whose answers are known: a square that accelerates to a
peak, freezes for a hit-stop and settles while the camera pans; a flat-background clip; an oscillation with a
known period; a clip animated on twos; audio clicks at known times. No real media, no vault.

    python -m unittest discover -s kit/scripts/tests -v
"""

import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))
import anim_analyze  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
W, H = 480, 270

# the moving-square clip's known answers (1-based frames at 30 fps)
SQ_PEAK = 20
SQ_HITSTOP = (20, 21, 23)
SQ_FRAMES = 45


def textured_bg(w, h, seed=3, lo=40, hi=200):
    rng = np.random.default_rng(seed)
    small = rng.integers(lo, hi, (h // 8 + 1, w // 8 + 1), dtype=np.uint8)
    return Image.fromarray(small).resize((w, h), Image.BILINEAR).convert("RGB")


def square_clip(out, pan=2, n=SQ_FRAMES, flat=False, ext="png"):
    """White square on a dark texture: still (frames 1-10), accelerating to its fastest frame 20, frozen 21-23 (hit-stop), decelerating
    24-30, still 31-45. The camera pans right `pan` px per frame (content moves left)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    big = (Image.new("RGB", (W + pan * n + 20, H), (50, 50, 50)) if flat
           else textured_bg(W + pan * n + 20, H, lo=20, hi=90))
    vel = dict(zip(range(11, 21), (2, 3, 4, 5, 6, 8, 10, 13, 17, 26)))     # a strike: fastest at frame 20
    vel.update({24: 6, 25: 4, 26: 3, 27: 2, 28: 1, 29: 1, 30: 1})
    x = 100.0
    for f in range(1, n + 1):
        x += vel.get(f, 0)
        cx = pan * (f - 1)
        im = big.crop((cx, 0, cx + W, H))
        sx = int(x - cx + 100)
        ImageDraw.Draw(im).rectangle([sx, 110, sx + 40, 150], fill=(250, 250, 250))
        im.save(out / f"f_{f:04d}.{ext}")
    return out


def osc_clip(out, period=12, n=60):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bg = textured_bg(W, H, seed=5)
    for f in range(1, n + 1):
        im = bg.copy()
        sx = int(200 + 70 * math.sin(2 * math.pi * (f - 1) / period))
        ImageDraw.Draw(im).rectangle([sx, 100, sx + 40, 160], fill=(30, 220, 60))
        im.save(out / f"f_{f:04d}.png")
    return out


def twos_clip(out, n=40):
    """Constant motion, each drawing held for two frames (animated on twos)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bg = textured_bg(W, H, seed=7)
    for f in range(1, n + 1):
        drawing = (f - 1) // 2
        im = bg.copy()
        sx = 40 + drawing * 18
        ImageDraw.Draw(im).rectangle([sx, 100, sx + 40, 160], fill=(240, 240, 40))
        im.save(out / f"f_{f:04d}.png")
    return out


def threes_clip(out, n=45):
    """Constant motion, each drawing held for three frames (animated on threes)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bg = textured_bg(W, H, seed=8)
    for f in range(1, n + 1):
        sx = 40 + ((f - 1) // 3) * 25
        im = bg.copy()
        ImageDraw.Draw(im).rectangle([sx, 100, sx + 40, 160], fill=(240, 120, 40))
        im.save(out / f"f_{f:04d}.png")
    return out


def bolt_x(f):
    """(critic r3) The critic's rifle bolt, 0-based frames at 60 fps, on ones: still, a 3 f snap back, a hold, a 2 f
    slam with overshoot, a settle, still."""
    if f < 40:
        return 300
    if f <= 42:
        return 300 - 80 * ((f - 39) / 3) ** 0.6
    if f <= 46:
        return 220
    if f <= 48:
        return 220 + 90 * ((f - 46) / 2)
    if f <= 52:
        return 310 - 10 * ((f - 48) / 4)
    return 300


def bolt_clip(out, n=120):
    """The critic's bolt-cycle clip: the support hand follows the bolt 1 f late, so frames 45-47 (1-based) are a
    3-frame hold inside motion that is otherwise on ones."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for f in range(n):
        im = Image.new("RGB", (640, 360), (40, 44, 52))
        d = ImageDraw.Draw(im)
        d.rectangle([80, 120, 140, 300], fill=(180, 150, 120))
        d.ellipse([85, 70, 135, 120], fill=(200, 170, 140))
        d.rectangle([140, 170, 520, 200], fill=(70, 70, 75))
        x = bolt_x(f)
        d.rectangle([x, 150, x + 50, 172], fill=(210, 210, 220))
        hx = bolt_x(max(0, f - 1)) + 20
        d.ellipse([hx, 128, hx + 28, 156], fill=(200, 170, 140))
        im.save(out / f"f_{f + 1:04d}.png")
    return out


def clicks_wav(path, seconds, clicks, rate=16000):
    x = np.zeros(int(seconds * rate), dtype=np.float32)
    rng = np.random.default_rng(0)
    for t in clicks:
        a = int(t * rate)
        x[a:a + int(0.03 * rate)] += (rng.standard_normal(int(0.03 * rate)) * 0.6).astype(np.float32)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def encode(frames_dir, out, fps=30, audio=None):
    """Encode f_%04d.png to H.264 (h264_nvenc when the GPU has it, else libx264) with optional audio."""
    out = Path(out)
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps), "-i",
            str(Path(frames_dir) / "f_%04d.png")]
    if audio:
        base += ["-i", str(audio), "-c:a", "aac", "-shortest"]
    for enc in (["-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "14"], ["-c:v", "libx264", "-crf", "12"]):
        r = subprocess.run(base + enc + ["-pix_fmt", "yuv420p", str(out)], capture_output=True)
        if r.returncode == 0 and out.is_file():
            return out
    raise RuntimeError("could not encode the synthetic clip")


def punch_x(f):
    """The critic's punch (60 fps, frames 1-150): still 1-20, a slow wind-up 21-60 (60 px back, ~1.5 px/frame),
    a 3-frame strike 61-63, frozen 64-68 (hit-stop), overshoot 69-72, settle 73-95, still 96-150."""
    if f <= 20:
        return 300
    if f <= 60:
        t = (f - 20) / 40
        return 300 - 60 * t * t * (3 - 2 * t)
    if f <= 63:
        return {61: 300, 62: 370, 63: 440}[f]
    if f <= 68:
        return 440
    if f <= 72:
        return 440 + 25 * (f - 68) / 4
    if f <= 95:
        t = (f - 72) / 23
        return 465 - 30 * t * t * (3 - 2 * t)
    return 435


PUNCH_PEAK, PUNCH_HITSTOP = 63, (63, 64, 68)


def punch_clip(out, pan=0, n=150, w=640, h=360):
    """Fist + arm on a fine random texture; the camera pans `pan` px/frame (content moves left)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    tex = (rng.random((h // 8, (w + 500) // 8, 3)) * 200 + 30).astype(np.uint8)
    # the critic's blocky texture, softened like a video encode would (raw nearest-neighbour blocks alias at the
    # analysis size far more than any real clip)
    tex = np.asarray(Image.fromarray(tex).resize((w + 500, h), Image.NEAREST).filter(ImageFilter.GaussianBlur(1.0)))
    for f in range(1, n + 1):
        cx = int(round((f - 1) * pan))
        im = Image.fromarray(tex[:, cx:cx + w].copy())
        d = ImageDraw.Draw(im)
        x = punch_x(f) - (f - 1) * pan
        d.rectangle([x, 160, x + 40, 200], fill=(255, 40, 40))
        d.rectangle([x - 120, 150, x, 210], fill=(40, 40, 255))
        im.save(out / f"f_{f:04d}.png")
    return out


def near(xs, target, tol=1):
    return any(abs(x - target) <= tol for x in xs)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="anim analyze "))   # a space in the path, on purpose

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSquare(Base):
    def test_peak_hitstop_holds_camera(self):
        fr = square_clip(self.tmp / "frames")
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-0001")
        self.assertTrue(near(res["peaks"], SQ_PEAK), res["peaks"])
        self.assertTrue(any(abs(h[0] - SQ_HITSTOP[0]) <= 1 and abs(h[1] - SQ_HITSTOP[1]) <= 1
                            and abs(h[2] - SQ_HITSTOP[2]) <= 1 for h in res["hitstop_candidates"]),
                        res["hitstop_candidates"])
        holds = res["holds"]
        self.assertTrue(any(a <= 2 and b >= 9 for a, b in holds), holds)        # the opening still
        self.assertTrue(any(a <= 32 and b == SQ_FRAMES for a, b in holds), holds)  # the final settle
        self.assertTrue(res["camera"]["moving"])
        self.assertAlmostEqual(float(np.median(res["camera"]["dx"][1:])), -2.0, delta=0.3)   # pan right
        # the pan is measured on every frame, also while the bright square out-shouts the background
        self.assertLess(max(abs(v + 2.0) for v in res["camera"]["dx"][1:]), 0.5, res["camera"]["dx"])
        self.assertEqual(res["cycle"], None)
        x, y, w, h = res["subject_box"]
        self.assertTrue(x < 260 and x + w > 300 and y < 115 and y + h > 145, res["subject_box"])
        self.assertIn(20, res["keypose_candidates"])

    def test_numbers_json_and_sheets(self):
        fr = square_clip(self.tmp / "frames", ext="jpg")
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-0002", fps_src=30)
        nums = json.loads((self.tmp / "out" / "numbers.json").read_text(encoding="utf-8"))
        for k in ("fps_src", "fps_analysis", "frames", "duration_s", "crop", "camera", "energy", "regions",
                  "holds", "peaks", "extremes", "smears", "hitstop_candidates", "cycle", "keypose_candidates",
                  "timing_60", "subject_box", "notes", "capture", "audio"):
            self.assertIn(k, nums)
        self.assertEqual(nums["frames"], SQ_FRAMES)
        self.assertEqual(len(nums["energy"]), SQ_FRAMES)
        self.assertAlmostEqual(max(nums["energy"]), 1.0, places=3)
        self.assertIn("shake_candidates", nums["camera"])
        self.assertEqual(len(nums["regions"]["cells"]), 9)
        self.assertTrue(nums["regions"]["first"])
        # 30 -> 60 fps: frame f becomes 2f - 1
        self.assertEqual(nums["timing_60"]["peaks"], [2 * f - 1 for f in nums["peaks"]])
        for key in ("contact", "keyposes", "strips", "onion", "motion"):
            p = Path(res["sheets"][key])
            self.assertTrue(p.is_file(), key)
            self.assertTrue(p.name.startswith("T-0002_"))
        self.assertEqual(Path(res["sheets"]["contact"]).suffix, ".jpg")
        self.assertEqual(Path(res["sheets"]["motion"]).suffix, ".png")
        with Image.open(res["sheets"]["strips"]) as im:
            self.assertEqual(im.width, 7 * 200)            # 7 frames per row: peak +-3

    def test_flat_background_static_camera(self):
        fr = square_clip(self.tmp / "frames", pan=0, flat=True)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-0003", sheets=False)
        self.assertFalse(res["camera"]["moving"], res["camera"]["dx"])
        self.assertTrue(near(res["peaks"], SQ_PEAK))

    def test_crop(self):
        fr = square_clip(self.tmp / "frames", pan=0)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-0004", crop=[0, 60, 480, 150], sheets=False)
        self.assertEqual(res["crop"], [0, 60, 480, 150])
        self.assertTrue(near(res["peaks"], SQ_PEAK))
        self.assertGreaterEqual(res["subject_box"][1], 60)
        with self.assertRaises(ValueError):
            anim_analyze.analyze(fr, 30, self.tmp / "out2", crop=[400, 0, 200, 100], sheets=False)


class TestCriticRound1(Base):
    """Regressions from the first critic round, on the critic's own punch (synthetic, answers known)."""

    def _same(self, a, b, tol=1):
        """Two lists of frames / ranges equal within tol frames, item by item."""
        self.assertEqual(len(a), len(b), (a, b))
        for x, y in zip(a, b):
            x, y = (x if isinstance(x, list) else [x]), (y if isinstance(y, list) else [y])
            self.assertTrue(all(abs(u - v) <= tol for u, v in zip(x, y)), (a, b))

    def test_slow_pan_is_compensated(self):
        # (critic B4) a 1 px/frame pan is sub-pixel at the analysis size; it used to swamp every hold
        r0 = anim_analyze.analyze(punch_clip(self.tmp / "p0", pan=0), 60, self.tmp / "o0", sheets=False)
        r1 = anim_analyze.analyze(punch_clip(self.tmp / "p1", pan=1), 60, self.tmp / "o1", sheets=False)
        self.assertFalse(r0["camera"]["moving"])
        self.assertTrue(r1["camera"]["moving"])
        self.assertAlmostEqual(float(np.median(r1["camera"]["dx"][1:])), -1.0, delta=0.1)
        for k in ("peaks", "holds", "hitstop_candidates"):
            self._same(r0[k], r1[k])
        self.assertTrue(near(r1["peaks"], PUNCH_PEAK))
        self.assertTrue(any(all(abs(u - v) <= 1 for u, v in zip(hs, PUNCH_HITSTOP)) for hs in r1["hitstop_candidates"]),
                        r1["hitstop_candidates"])

    def test_windup_is_slow_not_a_hold(self):
        # (critic B11) the ~1.5 px/frame wind-up 21-60 was swallowed by a hold 1-59
        r = anim_analyze.analyze(punch_clip(self.tmp / "p", pan=0), 60, self.tmp / "o", sheets=False)
        holds = r["holds"]
        self.assertFalse(any(a <= 50 and b >= 26 for a, b in holds), holds)
        self.assertTrue(any(a <= 2 and 18 <= b <= 22 for a, b in holds), holds)          # still 1-20
        self.assertTrue(any(abs(a - 64) <= 1 and abs(b - 68) <= 1 for a, b in holds), holds)   # hit-stop
        self.assertTrue(any(93 <= a <= 97 and b == 150 for a, b in holds), holds)          # still 96-150
        self.assertTrue(any(a <= 26 and b >= 50 for a, b in r["slow_segments"]), r["slow_segments"])
        self.assertIn("slow_segments", r["timing_60"])
        types = {d["frame"]: d["type"] for d in r["keypose_detail"]}
        self.assertEqual(types.get(PUNCH_PEAK), "contact")

    def test_subject_at_the_edge_is_not_a_camera_move(self):
        # (critic B5) a static GIF whose subject touches the frame edge read as moving: true
        for name, bg in (("flat", None), ("textured", textured_bg(200, 200, seed=4))):
            d = self.tmp / name
            d.mkdir()
            for f in range(24):
                im = bg.copy() if bg is not None else Image.new("RGB", (200, 200), (30, 30, 60))
                y = 175 - abs(math.sin(math.pi * f / 12)) * 120          # runs off the bottom edge
                ImageDraw.Draw(im).ellipse([60, y, 140, y + 80], fill=(255, 255, 255))
                im.save(d / f"f_{f + 1:04d}.png")
            r = anim_analyze.analyze(d, 12, self.tmp / ("o " + name), sheets=False)
            self.assertFalse(r["camera"]["moving"], (name, r["camera"]["dx"], r["camera"]["dy"]))
            self.assertLess(max(abs(v) for v in r["camera"]["dy"]), 0.5, name)

    def test_numbers_brief(self):
        fr = square_clip(self.tmp / "frames", n=30)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-B", sheets=False)
        brief = json.loads((self.tmp / "out" / "numbers_brief.json").read_text(encoding="utf-8"))
        self.assertNotIn("energy", brief)
        self.assertNotIn("dx", brief["camera"])
        self.assertNotIn("dy", brief["camera"])
        self.assertTrue(all("series" not in c and "peak_frame" in c for c in brief["regions"]["cells"]))
        self.assertEqual(brief["regions"]["order"], res["regions"]["order"])
        self.assertNotIn("duplicate_frames", brief["capture"])
        self.assertIn("duplicate_runs", brief["capture"])
        self.assertEqual(brief["holds"], res["holds"])

    def test_trim_and_decode_suspects_recorded(self):
        fr = square_clip(self.tmp / "frames")
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", sheets=False, trim=[1.0, 2.5],
                                   decode_errors={"events": 1, "lost_frames": 1, "suspect_frames": [SQ_PEAK]})
        self.assertEqual(res["trim"], [1.0, 2.5])
        de = res["decode_errors"]
        self.assertEqual(de["suspect_frames"], [SQ_PEAK])
        self.assertTrue(near(de["affected"]["peaks"], SQ_PEAK))
        self.assertTrue(de["affected"]["hitstop_candidates"])
        nums = json.loads((self.tmp / "out" / "numbers.json").read_text(encoding="utf-8"))
        self.assertEqual(nums["decode_errors"]["suspect_frames"], [SQ_PEAK])

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
    def test_slow_pan_through_h264(self):
        # the critic's exact route: encode, decode (GPU first), analyse
        import animlib
        out = {}
        for pan in (0, 1):
            clip = encode(punch_clip(self.tmp / f"src{pan}", pan=pan), self.tmp / f"pan {pan}.mp4", fps=60)
            try:
                ex = animlib.extract_frames(clip, self.tmp / f"fr{pan}", gpu=True)
            except animlib.GpuError:
                self.skipTest("no working GPU decode here")
            out[pan] = anim_analyze.analyze(self.tmp / f"fr{pan}", ex["fps"], self.tmp / f"o{pan}", sheets=False)
        for k in ("peaks", "holds", "hitstop_candidates"):
            self._same(out[0][k], out[1][k])
        self.assertAlmostEqual(float(np.median(out[1]["camera"]["dx"][1:])), -0.75, delta=0.1)   # 640 -> 480 px


class TestCycleAndCapture(Base):
    def test_cycle_period(self):
        fr = osc_clip(self.tmp / "frames", period=12, n=60)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-0005", sheets=False)
        self.assertIsNotNone(res["cycle"])
        self.assertAlmostEqual(res["cycle"]["period_frames"], 12, delta=1)
        self.assertFalse(res["camera"]["moving"])

    def test_twos(self):
        fr = twos_clip(self.tmp / "frames")
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", id="T-0006", sheets=False)
        cap = res["capture"]
        self.assertEqual(cap["stepping"], "twos", cap)
        self.assertGreaterEqual(len(cap["duplicate_frames"]), 15)
        self.assertAlmostEqual(cap["true_fps"], 15, delta=2)
        self.assertEqual(res["holds"], [])            # stepping is not a hold

    def test_ones_capture(self):
        fr = square_clip(self.tmp / "frames", pan=0)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", sheets=False)
        self.assertEqual(res["capture"]["stepping"], "ones")
        self.assertEqual(res["capture"]["true_fps"], 30)    # the 3 f hit-stop is a hold, not stepping

    def test_threes(self):
        res = anim_analyze.analyze(threes_clip(self.tmp / "frames"), 30, self.tmp / "out", sheets=False)
        self.assertEqual(res["capture"]["stepping"], "threes", res["capture"])
        self.assertAlmostEqual(res["capture"]["true_fps"], 10, delta=1.5)

    def test_hold_inside_motion_on_ones(self):
        # (critic r3) a real 60 fps clip on ones with a 3 f hold read true_fps 47.14 while stepping said "ones"
        res = anim_analyze.analyze(bolt_clip(self.tmp / "frames"), 60, self.tmp / "out", sheets=False)
        cap = res["capture"]
        self.assertEqual(cap["stepping"], "ones", cap)
        self.assertEqual(cap["true_fps"], 60, cap)
        self.assertTrue({45, 46, 47} <= set(cap["duplicate_frames"]), cap["duplicate_frames"])

    def test_isolated_short_holds_are_not_stepping(self):
        # runs of 1 and 2 duplicates scattered through motion on ones: holds, never twos/threes
        out = self.tmp / "frames"
        out.mkdir()
        bg = textured_bg(W, H, seed=11)
        x, held = 40.0, {12, 25, 26, 40, 52, 53}          # 1-based frames that repeat the previous drawing
        for f in range(1, 61):
            if f not in held:
                x += 5
            im = bg.copy()
            ImageDraw.Draw(im).rectangle([int(x), 100, int(x) + 40, 160], fill=(240, 240, 40))
            im.save(out / f"f_{f:04d}.png")
        cap = anim_analyze.analyze(out, 60, self.tmp / "out", sheets=False)["capture"]
        self.assertEqual(cap["stepping"], "ones", cap)
        self.assertEqual(cap["true_fps"], 60, cap)


class TestFrameNumbering(Base):
    """(critic r3) brief frames are 1-based and count from the trim; the data refs' spec is 0-based."""

    def test_brief_states_frame_base_and_trim_offset(self):
        fr = square_clip(self.tmp / "frames", n=30)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", sheets=False, trim=[0.5, 1.5])
        self.assertEqual(res["trim_offset_frames"], 15)
        self.assertEqual(res["timing_60"]["trim_offset_frames_60"], 30)
        brief = json.loads((self.tmp / "out" / "numbers_brief.json").read_text(encoding="utf-8"))
        self.assertEqual(brief["frame_base"], 1)
        self.assertEqual(brief["trim_offset_frames"], 15)
        self.assertIn("trim", brief["frame_note"])
        self.assertNotIn("spec_frame_offset", brief)
        res2 = anim_analyze.analyze(fr, 30, self.tmp / "out2", sheets=False)
        self.assertEqual(res2["trim_offset_frames"], 0)

    def test_data_brief_has_spec_offset(self):
        b = anim_analyze.brief({"id": "X", "source": "data", "frame_base": 1, "frames": 10})
        self.assertEqual(b["frame_base"], 1)
        self.assertEqual(b["spec_frame_offset"], -1)
        self.assertIn("spec f = brief f - 1", b["frame_note"])

    def test_onion_is_readable(self):
        # a small subject box used to make a thumbnail-sized onion sheet
        res = anim_analyze.analyze(square_clip(self.tmp / "frames", pan=0), 30, self.tmp / "out", id="T-ON")
        with Image.open(res["sheets"]["onion"]) as im:
            self.assertGreaterEqual(im.width, 640)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
class TestAudio(Base):
    def test_onsets_and_peak_sync(self):
        fr = square_clip(self.tmp / "frames", pan=0)
        wav = clicks_wav(self.tmp / "a.wav", 1.5, [0.5, 1.0])
        clip = encode(fr, self.tmp / "clip with audio.mp4", fps=30, audio=wav)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", sheets=False, source=str(clip))
        au = res["audio"]
        self.assertTrue(au["has_audio"])
        ms = [o["ms"] for o in au["onsets"]]
        self.assertTrue(any(abs(m - 500) <= 30 for m in ms), ms)
        self.assertTrue(any(abs(m - 1000) <= 30 for m in ms), ms)
        self.assertTrue(au["peak_sync"])
        p = next(s for s in au["peak_sync"] if abs(s["peak"] - SQ_PEAK) <= 1)
        self.assertEqual(p["onset_f"], 16)              # 0.5 s at 30 fps -> frame 16 (1-based)

    def test_no_audio_stream(self):
        fr = square_clip(self.tmp / "frames", pan=0, n=20)
        clip = encode(fr, self.tmp / "silent.mp4", fps=30)
        res = anim_analyze.analyze(fr, 30, self.tmp / "out", sheets=False, source=str(clip))
        self.assertFalse(res["audio"]["has_audio"])
        self.assertTrue(any("no audio stream" in n for n in res["notes"]))


class TestScaleAndCli(Base):
    def test_1200_frames_fast(self):
        out = self.tmp / "long"
        out.mkdir()
        bg = textured_bg(W, H, seed=9)
        for f in range(1, 1201):
            im = bg.copy()
            sx = int(200 + 80 * math.sin(f / 9.0))
            ImageDraw.Draw(im).rectangle([sx, 100, sx + 40, 160], fill=(200, 60, 200))
            im.save(out / f"f_{f:04d}.jpg", quality=85)
        t = time.time()
        res = anim_analyze.analyze(out, 60, self.tmp / "out", id="T-LONG")
        took = time.time() - t
        self.assertEqual(res["frames"], 1200)
        self.assertLess(took, 30, f"analysis of 1200 frames took {took:.1f}s")

    def test_cli(self):
        fr = square_clip(self.tmp / "frames", pan=0, n=24)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = anim_analyze.main([str(fr), "--fps", "30", "--out", str(self.tmp / "cli out"), "--id", "T-CLI"])
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "cli out" / "numbers.json").is_file())
        self.assertTrue((self.tmp / "cli out" / "sheets" / "T-CLI_motion.png").is_file())

    def test_too_few_frames(self):
        out = self.tmp / "two"
        square_clip(out, n=2)
        res = anim_analyze.analyze(out, 30, self.tmp / "out", id="T-2")
        self.assertTrue(any("frame" in n for n in res["notes"]))
        self.assertEqual(res["peaks"], [])


if __name__ == "__main__":
    unittest.main()
