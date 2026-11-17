"""Compare a recreation capture against the reference clip: the scoring half of the feedback loop.

Usage:
  python kit/scripts/anim_compare.py ANIM-COMBAT-0001 <capture.mp4 | capture_frames_dir> --vault V --spec-version 3 [--trim 12,58]
  python kit/scripts/anim_compare.py <ref_frames_dir> <capture> --fps 60

What it does
  1. extracts the capture's frames at the reference fps into <media>/iter_###/ (if a video; ffmpeg decodes on the GPU)
  2. trims leading/trailing stillness on both (so recording slack doesn't count);
     --trim a,b overrides that for the CAPTURE with an explicit 1-based frame range (--ref-trim a,b does the same for the reference)
  3. motion-energy curves -> DTW alignment -> metrics:
       duration_ratio      capture active length / reference active length (1.00 = same)
       spacing_corr        correlation of the energy curves resampled to equal length (easing/spacing similarity)
       keypose_offset      mean |frame offset| between reference key poses and the capture's nearest matching events
       hold_ratio          capture hold frames / reference hold frames
       peak_position       where the fastest frame sits (0-1) in each clip (anticipation vs follow-through balance)
       score               0-100 summary (timing only: POSE accuracy is judged by eye on compare_iter###.png)
  4. writes compare_iter###.png: each reference key pose next to the DTW-aligned capture frame
  5. appends the result to iterations.json and prints concrete retime hints.

Media: <vault>/11_ASSET_LIBRARY/_media/anim/<ID>/ (frames in its frames/ folder); the legacy <vault>/11_ASSET_LIBRARY/_media/frames/<ID>/
is used when the new folder has no frames. The vault comes from --vault or the ANIMSMITH_VAULT environment variable.

GPU first: video decode goes through animlib.extract_frames (ffmpeg -hwaccel cuda, with the same checks as the intake: a format
NVDEC can't take is never decoded on the CPU behind your back). Exit codes: 0 ok · 1 the capture couldn't be decoded (corrupt,
bad file) · 4 "gpu_failed" (the GPU path is broken) · 5 "nvdec_unsupported_format" (the GPU works but can't decode this file's
format). For 4 and 5, rerun with --gpu off to decode on the CPU only when the user has decided to.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FRAME_GLOBS = ("f_*.png", "f_*.jpg", "f_*.jpeg")


# ------------------------------------------------------------------ small helpers (self-contained)

def font(size=14):
    """Pillow's bundled default font (no system font paths)."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _resolve_vault(arg):
    try:
        from animlib import resolve_vault
    except ImportError:  # animlib is a sibling module; fall back to the same rule if it is missing
        v = (arg or os.environ.get("ANIMSMITH_VAULT", "")).strip().strip('"').strip("'").strip()
        if not v or not os.path.isdir(os.path.join(v, "11_ASSET_LIBRARY")):
            raise SystemExit("no vault: pass --vault <dir> or set ANIMSMITH_VAULT to a folder that contains 11_ASSET_LIBRARY")
        return v
    return str(resolve_vault(arg))


def list_frames(fdir):
    files = []
    for g in FRAME_GLOBS:
        files += glob.glob(os.path.join(fdir, g))
    return sorted(files)


def resolve_media(vault, aid):
    """(media_root, frames_dir). New layout _media/anim/<ID>/frames, legacy _media/frames/<ID>."""
    lib = os.path.join(vault, "11_ASSET_LIBRARY", "_media")
    new = os.path.join(lib, "anim", aid)
    legacy = os.path.join(lib, "frames", aid)
    for cand in (os.path.join(new, "frames"), new):
        if list_frames(cand):
            return new, cand
    if list_frames(legacy):
        return (new if os.path.isdir(new) else legacy), legacy
    return new, os.path.join(new, "frames")


def media_fps(root, frames_dir):
    for p in (os.path.join(root, "analysis", "numbers.json"), os.path.join(frames_dir, "meta.json"), os.path.join(root, "meta.json")):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
            except ValueError:
                continue
            v = d.get("fps_analysis") or d.get("extract_fps")
            if v:
                return float(v)
    return 60.0


def extract(video, out_dir, fps, gpu=True):
    """The capture's frames at exactly the reference fps, through animlib.extract_frames (GPU first, with the NVDEC format
    and decode-error checks the intake uses). Raises animlib.GpuError / NvdecUnsupported / AnimError."""
    import animlib
    os.makedirs(out_dir, exist_ok=True)
    for old in list_frames(out_dir):
        os.remove(old)
    return animlib.extract_frames(video, out_dir, fps_exact=fps, width=640, max_frames=100000, gpu=gpu)


# ------------------------------------------------------------------ motion analysis (energy curve, holds, key poses)

def load_frames(fdir, width=200):
    files = list_frames(fdir)
    if not files:
        sys.exit(f"no f_####.png/jpg frames in {fdir}")
    gray = []
    for f in files:
        im = Image.open(f).convert("L")
        h = max(1, int(im.height * width / im.width))
        gray.append(np.asarray(im.resize((width, h)), dtype=np.float32) / 255.0)
    return files, np.stack(gray)


def smooth(x, k=3):
    if len(x) < k:
        return x
    pad = np.pad(x, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def sharpness(g):
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def runs(mask, min_len):
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_len:
                out.append([start, i - 1])
            start = None
    return out


def analyse(fdir, fps):
    files, G = load_frames(fdir)
    n = len(G)
    diff = np.abs(np.diff(G, axis=0))                         # n-1 maps
    energy = np.concatenate([[0.0], diff.mean(axis=(1, 2))])  # energy[i] = change INTO frame i
    e = smooth(energy, 3)
    lo, hi = np.percentile(e[1:], 20) if n > 2 else 0, np.percentile(e[1:], 90) if n > 2 else 1
    thr_hold = lo + 0.15 * (hi - lo)
    holds = runs(e < thr_hold, max(2, round(fps / 20)))
    peaks = [i for i in range(1, n - 1) if e[i] >= e[i - 1] and e[i] > e[i + 1] and e[i] > np.percentile(e, 75)]
    extremes = [i for i in range(1, n - 1) if e[i] <= e[i - 1] and e[i] < e[i + 1] and e[i] < np.percentile(e, 60)]
    sharp = np.array([sharpness(g) for g in G])
    sm = smooth(sharp, 5)
    blur = [i for i in range(n) if sharp[i] < 0.6 * sm[i] and e[i] > np.percentile(e, 60)]
    acc = diff.max(axis=0) if len(diff) else np.zeros_like(G[0])
    mask = acc > max(0.08, np.percentile(acc, 95) * 0.5)
    ys, xs = np.nonzero(mask)
    H, W = G[0].shape
    if len(xs):
        x0, x1, y0, y1 = np.percentile(xs, 1), np.percentile(xs, 99), np.percentile(ys, 1), np.percentile(ys, 99)
        padx, pady = (x1 - x0) * 0.25 + 4, (y1 - y0) * 0.25 + 4
        bbox = [max(0, x0 - padx) / W, max(0, y0 - pady) / H, min(W, x1 + padx) / W, min(H, y1 + pady) / H]
    else:
        bbox = [0, 0, 1, 1]
    keys = {0, n - 1}
    for a, b in holds:
        keys |= {a, b}
    keys |= set(extremes) | set(peaks)
    keys = sorted(keys)
    rank = {i: 3 for h in holds for i in h}
    rank.update({i: max(rank.get(i, 0), 2) for i in extremes})
    rank.update({i: max(rank.get(i, 0), 1) for i in peaks})
    rank[0] = rank[n - 1] = 4
    thinned = []
    for k in keys:
        if thinned and k - thinned[-1] < 2:
            if rank.get(k, 0) > rank.get(thinned[-1], 0):
                thinned[-1] = k
            continue
        thinned.append(k)
    kind = {}
    for k in thinned:
        kind[k] = ("start" if k == 0 else "end" if k == n - 1 else
                   "hold" if rank.get(k) == 3 else "extreme" if rank.get(k) == 2 else "fast")
    moving = [i for i in range(n) if e[i] >= thr_hold]
    summary = {
        "frames": n, "fps": fps, "duration_s": round(n / fps, 3),
        "first_motion_frame": moving[0] + 1 if moving else None,
        "fastest_frame": int(np.argmax(e)) + 1,
        "settle_frame": moving[-1] + 1 if moving else None,
        "hold_frames_total": int(sum(b - a + 1 for a, b in holds)),
    }
    return {
        "source": os.path.abspath(fdir), "fps": fps, "summary": summary, "bbox_norm": [round(v, 4) for v in bbox],
        "energy": [round(float(v), 5) for v in e],
        "holds": [[a + 1, b + 1] for a, b in holds], "peaks": [p + 1 for p in peaks],
        "extremes": [x + 1 for x in extremes], "blur_or_smear": [b + 1 for b in blur],
        "keypose_candidates": [{"frame": k + 1, "type": kind[k], "energy": round(float(e[k]), 5)} for k in thinned],
    }, files


def crop(im, bbox):
    W, H = im.size
    return im.crop((int(bbox[0] * W), int(bbox[1] * H), int(bbox[2] * W), int(bbox[3] * H)))


def active_range(a):
    s = a["summary"]
    lo = max(1, (s["first_motion_frame"] or 1) - 1)
    hi = s["settle_frame"] or s["frames"]
    return lo, hi


def parse_trim(text, n):
    """'a,b' (1-based, inclusive) -> (a, b) clamped to 1..n."""
    try:
        a, b = (int(float(x)) for x in text.split(","))
    except ValueError:
        raise SystemExit(f"--trim wants two frame numbers like 12,58, got {text!r}")
    a, b = max(1, min(a, b)), min(n, max(a, b))
    if b - a < 1:
        raise SystemExit(f"--trim {text} leaves fewer than 2 frames (the clip has {n})")
    return a, b


# ------------------------------------------------------------------ DTW

def dtw_reference(x, y):
    """The original pure-Python double loop (kept for the equivalence test)."""
    n, m = len(x), len(y)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = abs(x[i - 1] - y[j - 1])
            D[i, j] = c + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    return _backtrack(D, n, m)


def _backtrack(D, n, m):
    i, j, path = n, m, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        k = int(np.argmin([D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]]))
        i, j = (i - 1, j - 1) if k == 0 else (i - 1, j) if k == 1 else (i, j - 1)
    return list(reversed(path))


def dtw(x, y):
    """Dynamic time warping path, vectorised along anti-diagonals (cells on one diagonal only depend on the two before it)."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n, m = len(x), len(y)
    C = np.abs(x[:, None] - y[None, :])
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0
    for d in range(2, n + m + 1):
        i = np.arange(max(1, d - m), min(n, d - 1) + 1)
        j = d - i
        best = np.minimum(np.minimum(D[i - 1, j], D[i, j - 1]), D[i - 1, j - 1])
        D[i, j] = C[i - 1, j - 1] + best
    return _backtrack(D, n, m)


def resample(v, n):
    return np.interp(np.linspace(0, len(v) - 1, n), np.arange(len(v)), v)


# ------------------------------------------------------------------ compare

def compare(ref_dir, cap_dir, fps, trim=None, ref_trim=None):
    ra, rfiles = analyse(ref_dir, fps)
    ca, cfiles = analyse(cap_dir, fps)
    r0, r1 = parse_trim(ref_trim, ra["summary"]["frames"]) if ref_trim else active_range(ra)
    c0, c1 = parse_trim(trim, ca["summary"]["frames"]) if trim else active_range(ca)
    re = np.array(ra["energy"][r0 - 1:r1])
    ce = np.array(ca["energy"][c0 - 1:c1])
    re_n = re / (re.max() or 1)
    ce_n = ce / (ce.max() or 1)
    path = dtw(re_n, ce_n)
    ref_to_cap = {}
    for i, j in path:
        ref_to_cap.setdefault(i, j)
    n = max(len(re_n), len(ce_n), 2)
    corr = float(np.corrcoef(resample(re_n, n), resample(ce_n, n))[0, 1]) if len(re_n) > 2 and len(ce_n) > 2 else 0.0
    corr = 0.0 if np.isnan(corr) else corr
    cap_events = [k["frame"] - c0 for k in ca["keypose_candidates"] if c0 <= k["frame"] <= c1]
    offsets, pairs = [], []
    for k in ra["keypose_candidates"]:
        if not (r0 <= k["frame"] <= r1):
            continue
        i = k["frame"] - r0
        j = ref_to_cap.get(i, int(round(i * len(ce_n) / max(len(re_n), 1))))
        scaled = i * len(ce_n) / max(len(re_n), 1)
        if cap_events:
            nearest = min(cap_events, key=lambda e: abs(e - scaled))
            offsets.append(abs(nearest - i))
        pairs.append((k["frame"], j + c0, k["type"]))
    dur = len(ce_n) / max(len(re_n), 1)
    rh = sum(b - a + 1 for a, b in ra["holds"] if a >= r0 and b <= r1)
    ch = sum(b - a + 1 for a, b in ca["holds"] if a >= c0 and b <= c1)
    hold_ratio = (ch / rh) if rh else (1.0 if ch == 0 else 2.0)
    rp = (int(np.argmax(re_n))) / max(len(re_n) - 1, 1)
    cp = (int(np.argmax(ce_n))) / max(len(ce_n) - 1, 1)
    off = float(np.mean(offsets)) if offsets else 0.0
    score = (40 * max(0.0, corr) + 25 * max(0.0, 1 - off / 6) + 15 * max(0.0, 1 - abs(1 - dur))
             + 10 * max(0.0, 1 - abs(1 - min(hold_ratio, 2))) + 10 * max(0.0, 1 - abs(rp - cp) * 4))
    hints = []
    if dur > 1.08:
        hints.append(f"recreation is {dur - 1:.0%} slower overall: remove ~{(len(ce_n) - len(re_n))} frames (polish --retime).")
    elif dur < 0.92:
        hints.append(f"recreation is {1 - dur:.0%} faster overall: add ~{(len(re_n) - len(ce_n))} frames.")
    if rp - cp > 0.08:
        hints.append(f"fastest frame comes too EARLY ({cp:.0%} vs ref {rp:.0%}): lengthen anticipation / hold before the strike.")
    elif cp - rp > 0.08:
        hints.append(f"fastest frame comes too LATE ({cp:.0%} vs ref {rp:.0%}): shorten anticipation, extend follow-through.")
    if hold_ratio < 0.6 and rh >= 3:
        hints.append(f"reference holds {rh} frames, recreation {ch}: add held key poses (moving holds) at the extremes.")
    elif hold_ratio > 1.6:
        hints.append(f"recreation holds {ch} frames vs ref {rh}: too much dead time; tighten.")
    if corr < 0.6:
        hints.append("spacing differs (low energy correlation): check easing, snappier into contacts, softer out of extremes.")
    return {"ref_active": [r0, r1], "cap_active": [c0, c1], "duration_ratio": round(dur, 3), "spacing_corr": round(corr, 3),
            "keypose_offset": round(off, 2), "hold_ratio": round(hold_ratio, 3), "peak_position": [round(rp, 3), round(cp, 3)],
            "score": round(score, 1), "hints": hints, "pairs": pairs,
            "ref_bbox": ra["bbox_norm"], "cap_bbox": ca["bbox_norm"]}, rfiles, cfiles


def sheet(res, rfiles, cfiles, out, tile=200):
    pairs = res["pairs"][:20]
    f = font(14)
    im = Image.new("RGB", (tile * 2 + 10, max(1, len(pairs)) * (tile + 20) + 44), "white")
    d = ImageDraw.Draw(im)
    d.text((4, 2), "REFERENCE  |  RECREATION", fill=(0, 0, 0), font=f)
    d.text((4, 20), f"score {res['score']}  dur x{res['duration_ratio']}  spacing r={res['spacing_corr']}", fill=(0, 0, 0), font=f)
    for row, (rf, cf, typ) in enumerate(pairs):
        y = 44 + row * (tile + 20)
        a = crop(Image.open(rfiles[rf - 1]).convert("RGB"), res["ref_bbox"])
        b = crop(Image.open(cfiles[min(cf, len(cfiles)) - 1]).convert("RGB"), res["cap_bbox"])
        a.thumbnail((tile, tile))
        b.thumbnail((tile, tile))
        im.paste(a, ((tile - a.width) // 2, y + 18))
        im.paste(b, (tile + 10 + (tile - b.width) // 2, y + 18))
        d.text((4, y + 2), f"ref f{rf} ({typ})", fill=(0, 0, 160), font=f)
        d.text((tile + 14, y + 2), f"cap f{cf}", fill=(160, 0, 0), font=f)
    im.save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref", help="asset id or reference frames dir")
    ap.add_argument("capture", help="capture video or frames dir")
    ap.add_argument("--vault", help="vault folder (else ANIMSMITH_VAULT); only needed when ref is an asset id")
    ap.add_argument("--fps", type=float, default=0)
    ap.add_argument("--spec-version", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--trim", help="a,b: use only capture frames a..b (1-based, inclusive) instead of the automatic stillness trim")
    ap.add_argument("--ref-trim", help="a,b: same, for the reference clip")
    ap.add_argument("--gpu", choices=["on", "off"], default="on", help="ffmpeg decode on the GPU (default); off = CPU, only when you decided to")
    a = ap.parse_args(argv)
    if os.path.isdir(a.ref):
        ref_dir = a.ref
        root = os.path.dirname(os.path.normpath(ref_dir)) if os.path.basename(os.path.normpath(ref_dir)) == "frames" else ref_dir
    else:
        vault = _resolve_vault(a.vault)
        root, ref_dir = resolve_media(vault, a.ref)
    fps = a.fps or media_fps(root, ref_dir)
    log_path = os.path.join(root, "iterations.json")
    log = json.load(open(log_path, encoding="utf-8")) if os.path.exists(log_path) else []
    it = len(log) + 1
    if os.path.isdir(a.capture):
        cap_dir = a.capture
    else:
        cap_dir = os.path.join(root, f"iter_{it:03d}")
        import animlib
        try:
            ex = extract(a.capture, cap_dir, fps, gpu=a.gpu == "on")
        except animlib.GpuError as e:
            print(f"{e} Not falling back to the CPU; rerun with --gpu off only if the user wants that.", file=sys.stderr)
            return 4
        except animlib.NvdecUnsupported as e:
            print(str(e), file=sys.stderr)
            return 5
        except Exception as e:  # a corrupt or unreadable capture
            print(f"{animlib.error_code(e)}: could not decode the capture: {e}", file=sys.stderr)
            return 1
        for n in ex.get("notes") or []:
            print("  note: " + n)
    res, rfiles, cfiles = compare(ref_dir, cap_dir, fps, trim=a.trim, ref_trim=a.ref_trim)
    out_png = os.path.join(root, f"compare_iter{it:03d}.png")
    sheet(res, rfiles, cfiles, out_png)
    entry = {"iter": it, "date": datetime.date.today().isoformat(), "spec_version": a.spec_version,
             "capture": os.path.abspath(a.capture), "note": a.note, **{k: v for k, v in res.items() if k not in ("pairs", "ref_bbox", "cap_bbox")}}
    log.append(entry)
    json.dump(log, open(log_path, "w", encoding="utf-8"), indent=1)
    print(f"iter {it}: score {res['score']}  duration x{res['duration_ratio']}  spacing r={res['spacing_corr']}  "
          f"keypose offset {res['keypose_offset']}f  hold ratio {res['hold_ratio']}  peak pos ref/cap {res['peak_position']}")
    for h in res["hints"] or ["timing matches within tolerance: judge poses on the compare sheet."]:
        print("  - " + h)
    if len(log) > 1:
        print("  trend: " + " -> ".join(str(e["score"]) for e in log))
    print(f"wrote {out_png} and {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
