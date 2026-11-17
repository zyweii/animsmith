"""animsmith anim_analyze v2: measure the motion in a folder of extracted frames (f_0001.jpg ...).

    python anim_analyze.py <frames_dir> --fps N --out DIR [--id ID] [--crop x,y,w,h] [--source CLIP] [--fps-src N]

Writes DIR/numbers.json (+ numbers_brief.json: the same minus per-frame series) and five sheets in DIR/sheets/ (or sheets_dir when called from Python):
  <ID>_contact.jpg   4x4 frames spread over the clip
  <ID>_keyposes.jpg  key-pose candidates cropped to the subject, labelled with frame numbers
  <ID>_strips.jpg    every frame +-3 around each of the (up to) 4 biggest motion peaks, one row per peak
  <ID>_onion.jpg     key poses ghosted over the background
  <ID>_motion.png    subject energy, camera shift and the 3x3 region energies over time

Everything in numbers.json is MEASURED from pixels (and audio, when a source clip with sound is given). Frame
numbers are 1-based f_#### indices at the analysis fps; `timing_60` holds the same lists converted to 60 fps.
Camera shift is the global content shift between consecutive frames (phase correlation, numpy FFT), checked
against the frame border so a moving subject on a flat background isn't mistaken for a camera move.
Stdlib + numpy + Pillow (+ ffmpeg only for --source audio).
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import animlib  # noqa: E402

VERSION = "anim_analyze v2"
WORK_W = 240          # analysis width in pixels (frames are <= 480 wide; half is plenty for motion)
BLOCK = 4             # coarse grid for stored diff maps (regions, subject box)
NOISE = 0.03          # per-pixel diff below this is compression noise
CELL_NAMES = ["top-left", "top-center", "top-right", "mid-left", "center", "mid-right",
              "bottom-left", "bottom-center", "bottom-right"]
MEASURED = ("MEASURED by anim_analyze v2 from the frames' pixels (and the source's audio when present). "
            "Frame numbers are 1-based f_#### indices at fps_analysis.")


# ---------------------------------------------------------------- loading

def list_frames(frames_dir):
    d = Path(frames_dir)
    files = sorted(list(d.glob("f_*.jpg")) + list(d.glob("f_*.png")) + list(d.glob("f_*.jpeg")))
    return files


def load_stack(files, crop=None, work_w=WORK_W):
    """Grayscale float32 stack (n, h, w) at work_w wide over the crop box (frame px). Returns (G, scale) where
    scale = frame px per work px."""
    with Image.open(files[0]) as im:
        W, H = im.size
    x, y, w, h = crop if crop else (0, 0, W, H)
    ww = min(work_w, w)
    hh = max(8, int(round(h * ww / w)))
    G = np.empty((len(files), hh, ww), dtype=np.float32)
    for i, f in enumerate(files):
        with Image.open(f) as im:
            if im.format == "JPEG" and not crop:
                im.draft("L", (ww, hh))
            im = im.convert("L")
            if im.size != (W, H):
                im = im.resize((W, H))
            if crop:
                im = im.crop((x, y, x + w, y + h))
            G[i] = np.asarray(im.resize((ww, hh), Image.BILINEAR), dtype=np.float32) / 255.0
    return G, w / ww


def smooth(x, k=3):
    x = np.asarray(x, dtype=np.float64)
    if len(x) < k:
        return x.copy()
    if k == 3:
        ker = np.array([1.0, 2.0, 1.0]) / 4.0
    else:
        ker = np.ones(k) / k
    pad = np.pad(x, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, ker, mode="valid")


def runs(mask, min_len=1):
    """[[a, b]] 0-based inclusive runs of True of at least min_len."""
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_len:
                out.append([start, i - 1])
            start = None
    return out


# ---------------------------------------------------------------- camera

def phase_shifts(G, chunk=96, top=3, mask=None):
    """Candidate content shifts from frame i-1 to i (work px): the `top` strongest phase-correlation peaks per
    frame, strongest first, as [(dy, dx, height)]. A bright moving subject can out-shout the background, so the
    camera check below picks among them."""
    n, h, w = G.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    if mask is not None:
        win = win * mask                     # 0 over the subject: measure the background only
    cands = [[] for _ in range(n)]
    prevF = None
    for s in range(0, n, chunk):
        blk = G[s:s + chunk]
        if mask is not None:
            m_ = mask > 0
            means = blk[:, m_].mean(axis=1)[:, None, None]
        else:
            means = blk.mean(axis=(1, 2), keepdims=True)
        blk = (blk - means) * win
        F = np.fft.rfft2(blk)
        Fa = F if prevF is None else np.concatenate([prevF[None], F])
        base = s if prevF is None else s - 1
        if len(Fa) > 1:
            R = Fa[1:] * np.conj(Fa[:-1])
            R /= np.abs(R) + 1e-9
            r = np.fft.irfft2(R, s=(h, w))
            for k in range(len(r)):
                rk = r[k]
                work = rk.copy()
                out = []
                for _ in range(top):
                    py, px = np.unravel_index(int(work.argmax()), (h, w))
                    b = float(rk[py, px])

                    def para(a, c):
                        den = a - 2 * b + c
                        return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) if abs(den) > 1e-12 else 0.0

                    oy = para(rk[(py - 1) % h, px], rk[(py + 1) % h, px])
                    ox = para(rk[py, (px - 1) % w], rk[py, (px + 1) % w])
                    dy = (py - h if py > h // 2 else py) + oy
                    dx = (px - w if px > w // 2 else px) + ox
                    out.append((dy, dx, b))
                    ys = [(py + j) % h for j in range(-1, 2)]
                    xs = [(px + j) % w for j in range(-1, 2)]
                    work[np.ix_(ys, xs)] = -np.inf
                cands[base + 1 + k] = out
        prevF = F[-1]
    return cands


def _shifted_pair(a, b, dy, dx):
    """Overlapping views (a_part, b_part) where b is a shifted by (dy, dx): b[y, x] ~ a[y - dy, x - dx]."""
    h, w = a.shape
    ys, ye = max(0, dy), min(h, h + dy)
    xs, xe = max(0, dx), min(w, w + dx)
    return a[ys - dy:ye - dy, xs - dx:xe - dx], b[ys:ye, xs:xe], (ys, ye, xs, xe)


def _feather(m, k):
    """Separable box blur (edge-padded) of a 2-D mask."""
    pad = k // 2
    ker = np.ones(k, dtype=np.float32) / k
    a = np.pad(m, ((0, 0), (pad, pad)), mode="edge")
    a = np.apply_along_axis(lambda r: np.convolve(r, ker, mode="valid"), 1, a)
    a = np.pad(a, ((pad, pad), (0, 0)), mode="edge")
    return np.apply_along_axis(lambda c: np.convolve(c, ker, mode="valid"), 0, a).astype(np.float32)


def shift_img(a, dy, dx):
    """a translated by (dy, dx) work px with bilinear interpolation: out[y, x] = a[y - dy, x - dx]. Edge pixels are
    replicated, so the outer ceil(|d|) + 1 px are not trustworthy (see valid_mask)."""
    h, w = a.shape
    iy, ix = math.floor(dy), math.floor(dx)
    fy, fx = dy - iy, dx - ix
    R = max(abs(iy), abs(ix)) + 2
    p = np.pad(a, R, mode="edge")

    def sl(oy, ox):                       # a[y - oy, x - ox]
        return p[R - oy:R - oy + h, R - ox:R - ox + w]

    out = (1 - fy) * (1 - fx) * sl(iy, ix)
    if fy:
        out = out + fy * (1 - fx) * sl(iy + 1, ix)
    if fx:
        out = out + (1 - fy) * fx * sl(iy, ix + 1)
    if fy and fx:
        out = out + fy * fx * sl(iy + 1, ix + 1)
    return out.astype(np.float32)


def valid_mask(shape, dy, dx):
    h, w = shape
    m = np.ones((h, w), dtype=bool)
    by, bx = int(math.ceil(abs(dy))) + 1, int(math.ceil(abs(dx))) + 1
    m[:by] = m[-by:] = False
    m[:, :bx] = m[:, -bx:] = False
    return m


def comp_pair(a, b, dy, dx):
    """|b - a shifted by (dy, dx)|, sub-pixel and symmetric (a moves +d/2, b moves -d/2, so both get the same
    interpolation blur), plus the mask of pixels the shift leaves valid."""
    if dy == 0 and dx == 0:
        return np.abs(b - a), None
    d = np.abs(shift_img(b, -dy / 2, -dx / 2) - shift_img(a, dy / 2, dx / 2))
    return d, valid_mask(a.shape, dy, dx)


def lk_refine(a, b, d0, m, iters=4):
    """Global translation (dy, dx) with b ~ a shifted by d, refined from d0 by Lucas-Kanade over the pixels in
    mask m (the background). Returns (dy, dx) or None when the mask has too little texture to tell."""
    dy, dx = float(d0[0]), float(d0[1])
    for _ in range(iters):
        aw = shift_img(a, dy, dx)
        gy, gx = np.gradient(aw)
        vm = m & valid_mask(a.shape, dy, dx)
        if vm.sum() < 50:
            return None
        gyv, gxv, r = gy[vm], gx[vm], (b - aw)[vm]
        A = np.array([[np.dot(gyv, gyv), np.dot(gyv, gxv)], [np.dot(gyv, gxv), np.dot(gxv, gxv)]])
        if np.linalg.det(A) <= 1e-9 * (np.trace(A) ** 2 + 1e-12) or np.trace(A) < 1e-6:
            return None
        step = -np.linalg.solve(A, np.array([np.dot(gyv, r), np.dot(gxv, r)]))
        step = np.clip(step, -1.0, 1.0)
        dy, dx = dy + float(step[0]), dx + float(step[1])
        if abs(step[0]) < 0.01 and abs(step[1]) < 0.01:
            break
    return dy, dx


CAM_BLOCKS = (6, 8)       # rows, cols of the voting grid
CAM_TEX = 0.012           # mean |gradient| a block needs to show a camera move at all
CAM_STATIC = 0.006        # mean |diff| below this: the block didn't change


def _block_means(x, m, grid=CAM_BLOCKS):
    """Per-block mean of x over mask m and the masked fraction, on a rows x cols grid (vectorised)."""
    h, w = x.shape
    gr, gc = grid
    ys = np.linspace(0, h, gr + 1).astype(int)[:-1]
    xs = np.linspace(0, w, gc + 1).astype(int)[:-1]
    mf = m.astype(np.float32)
    sx = np.add.reduceat(np.add.reduceat(x * mf, ys, axis=0), xs, axis=1)
    sm = np.add.reduceat(np.add.reduceat(mf, ys, axis=0), xs, axis=1)
    size = np.outer(np.diff(np.append(ys, h)), np.diff(np.append(xs, w)))
    mean = np.where(sm > 0, sx / np.maximum(sm, 1), 0.0)
    return mean.ravel().astype(np.float64), (sm / size).ravel()


def estimate_camera(G, cands, mask=None):
    """Per frame, the camera's content shift (dy, dx) in work px, decided by the background blocks.

    The frame is cut into a 6x8 grid; blocks over the subject (mask 0) and blocks too flat to show a shift are
    left out. Each candidate shift (the phase-correlation peaks, refined to sub-pixel by Lucas-Kanade over the
    background) must explain at least half of the remaining blocks, and more of them than "no shift" does, before
    it counts as a camera move. So a subject touching the frame edge can't pass for a pan (it covers only a few
    blocks), and a flat background reads as "can't tell" (static), never as motion.
    Returns ((n, 2) array, count of frames whose background was too flat to tell)."""
    n, h, w = G.shape
    bg = np.ones((h, w), dtype=bool) if mask is None else (mask > 0.5)
    out = np.zeros((n, 2))
    flat = 0
    nb = CAM_BLOCKS[0] * CAM_BLOCKS[1]
    for i in range(1, n):
        a, b = G[i - 1], G[i]
        d0 = np.abs(b - a)
        r0, frac = _block_means(d0, bg)
        gy, gx = np.gradient(a)
        tex, _ = _block_means(np.abs(gy) + np.abs(gx), bg)
        inf = (frac >= 0.3) & (tex >= CAM_TEX)
        k_inf = int(inf.sum())
        if k_inf < max(4, int(0.2 * nb)):
            if float(d0.mean()) > CAM_STATIC:
                flat += 1
            continue
        moved = inf & (r0 > CAM_STATIC)
        if moved.sum() < 0.5 * k_inf:
            continue                      # most of the background didn't change: no camera move
        best, best_sup = None, 0
        starts = [(dy, dx) for dy, dx, _h in (cands[i] or []) if abs(dy) < h / 3 and abs(dx) < w / 3]
        starts.append((0.0, 0.0))
        tried = []
        for st in starts:
            if best_sup >= 0.8 * k_inf:
                break                     # clear winner already
            if any(abs(st[0] - t[0]) < 0.5 and abs(st[1] - t[1]) < 0.5 for t in tried):
                continue                  # LK from here lands where an earlier start did
            d = lk_refine(a, b, st, bg)
            if d is None or abs(d[0]) >= h / 3 or abs(d[1]) >= w / 3:
                continue
            if any(abs(d[0] - t[0]) < 0.05 and abs(d[1] - t[1]) < 0.05 for t in tried):
                continue
            tried.append(d)
            dc, vm = comp_pair(a, b, d[0], d[1])
            rc, fr2 = _block_means(dc, bg & vm if vm is not None else bg)
            sup = int(np.sum(inf & (fr2 >= 0.15) & ((rc < 0.6 * r0) | (rc <= CAM_STATIC)) & (r0 > CAM_STATIC)))
            if sup > best_sup:
                best, best_sup = d, sup
        if best is not None and best_sup >= 0.5 * k_inf and max(abs(best[0]), abs(best[1])) >= 0.05:
            out[i] = best
    return out, flat


def span_energy(G, cam, i, j):
    """Compensated motion energy from frame i to frame j (0-based, i < j), on the same scale as one frame of D:
    the camera shift is the sum of the per-frame shifts in between."""
    n, h, w = G.shape
    gh, gw = h // BLOCK, w // BLOCK
    dy, dx = float(cam[i + 1:j + 1, 0].sum()), float(cam[i + 1:j + 1, 1].sum())
    d, vm = comp_pair(G[i], G[j], dy, dx)
    if vm is not None:
        d = np.where(vm, d, 0.0)
    return float(np.maximum(d - NOISE, 0.0)[:gh * BLOCK, :gw * BLOCK].sum())


def comp_diffs(G, cam, crop_valid=True):
    """Camera-compensated absolute differences (sub-pixel), reduced to a coarse BLOCK grid: D (n, gh, gw), plus raw
    (uncompensated) per-frame mean diff and coarse max for duplicate detection."""
    n, h, w = G.shape
    gh, gw = h // BLOCK, w // BLOCK
    D = np.zeros((n, gh, gw), dtype=np.float32)
    raw_mean = np.zeros(n)
    raw_max = np.zeros(n)
    for i in range(1, n):
        rd = np.abs(G[i] - G[i - 1])
        raw_mean[i] = rd.mean()
        cb = rd[:gh * BLOCK, :gw * BLOCK].reshape(gh, BLOCK, gw, BLOCK).mean(axis=(1, 3))
        raw_max[i] = cb.max() if cb.size else 0.0
        dy, dx = float(cam[i, 0]), float(cam[i, 1])
        if dy == 0 and dx == 0:
            d = rd
        else:
            d, vm = comp_pair(G[i - 1], G[i], dy, dx)
            d = np.where(vm, d, 0.0)
        d = np.maximum(d - NOISE, 0.0)
        D[i] = d[:gh * BLOCK, :gw * BLOCK].reshape(gh, BLOCK, gw, BLOCK).sum(axis=(1, 3))
    if n > 1:
        D[0] = D[1]
    return D, raw_mean, raw_max


# ---------------------------------------------------------------- measurements

def subject_box(D):
    """[x0, y0, x1, y1] in coarse cells, from where compensated motion accumulates."""
    acc = D.sum(axis=0)
    gh, gw = acc.shape
    if acc.max() <= 0:
        return None
    thr = 0.25 * np.percentile(acc[acc > 0], 99) if (acc > 0).any() else 0
    ys, xs = np.nonzero(acc >= max(thr, 1e-6))
    if len(xs) == 0:
        return None
    x0, x1 = np.percentile(xs, 1), np.percentile(xs, 99)
    y0, y1 = np.percentile(ys, 1), np.percentile(ys, 99)
    px, py = (x1 - x0) * 0.1 + 1, (y1 - y0) * 0.1 + 1
    return [int(max(0, math.floor(x0 - px))), int(max(0, math.floor(y0 - py))),
            int(min(gw, math.ceil(x1 + px + 1))), int(min(gh, math.ceil(y1 + py + 1)))]


def capture_stats(raw_mean, raw_max, fps, energy_norm):
    """Duplicate frames, stepping, a true-fps estimate and dropped-frame suspects."""
    n = len(raw_mean)
    dup = np.zeros(n, dtype=bool)
    if n > 1:
        dup[1:] = (raw_mean[1:] < 0.0025) & (raw_max[1:] < 0.012)
    dup_runs = runs(dup, 1)
    # (critic r3) stepping is a PERIODIC pattern: runs of 1 duplicate with one new drawing between them (twos) or 2
    # with one between (threes). A run counts only inside a chain of >= 3 such runs, each separated from the next by
    # exactly one changed frame; an isolated run (a 1-3 f hold inside motion on ones) is a hold, not stepping.
    cand = [r for r in dup_runs if (r[1] - r[0] + 1) <= 2 and r[0] - 1 >= 1 and r[1] + 1 < n
            and not dup[r[0] - 1] and not dup[r[1] + 1]]
    short, chain = [], []
    for r in cand + [None]:
        if r is not None and chain and r[0] == chain[-1][1] + 2:
            chain.append(r)
            continue
        if len(chain) >= 3:
            short.extend(chain)
        chain = [r] if r is not None else []
    hold_frames = sum(r[1] - r[0] + 1 for r in dup_runs) - sum(r[1] - r[0] + 1 for r in short)
    moving = n - 1 - hold_frames
    short_frames = sum(r[1] - r[0] + 1 for r in short)
    stepping, step_len = "ones", 0
    if moving > 0 and short_frames / moving >= 0.25 and len(short) >= 3:
        lens = [r[1] - r[0] + 1 for r in short]
        vals, counts = np.unique(lens, return_counts=True)
        mode = int(vals[counts.argmax()])
        share = counts.max() / len(lens)
        if share >= 0.7 and mode in (1, 2):
            stepping, step_len = ("twos" if mode == 1 else "threes"), mode
        else:
            stepping = "mixed"
    else:
        short = []
    # on ones every moving frame is a new drawing: the true rate is the analysis rate, whatever holds the clip has
    true_fps = fps * (1 - short_frames / moving) if (short and moving > 0) else fps
    # dropped frames: one frame jumps ~2x its two (similar) neighbours inside smooth motion
    E = np.asarray(energy_norm, dtype=np.float64)
    dropped = []
    for i in range(2, n - 1):
        a, c = E[i - 1], E[i + 1]
        m = (a + c) / 2
        if a > 0.15 and c > 0.15 and E[i] >= 1.8 * m and abs(a - c) < 0.3 * m:
            dropped.append(i + 1)
    return {"true_fps": round(float(true_fps), 2), "duplicate_frames": [int(i) + 1 for i in np.nonzero(dup)[0]],
            "dropped_frame_suspects": dropped, "stepping": stepping,
            "method": "duplicate = mean abs diff < 0.0025 and no 4x4 block > 0.012 (0..1 luma); stepping only from "
                      "periodic duplicates (chains of >= 3 runs of 1 (twos) or 2 (threes) duplicates, one new "
                      "drawing between each); isolated duplicate runs are holds; on ones true_fps = fps_analysis"}, \
        short, step_len


def redistribute(raw, short_runs, step_len):
    """On twos/threes, spread each drawing's change over its held frames so stepping doesn't read as holds."""
    e = raw.copy()
    if not step_len:
        return e
    n = len(e)
    for a, b in short_runs:
        if b - a + 1 > step_len:
            continue
        nxt = b + 1
        if nxt < n:
            share = e[nxt] / (b - a + 2)
            e[a:nxt + 1] = share
    return e


def find_peaks(es, raw, floor):
    n = len(es)
    peaks = []
    for i in range(1, n - 1):
        if es[i] >= es[i - 1] and es[i] > es[i + 1] and es[i] >= floor:
            # prominence: drop to either side before a higher value
            l = i
            lmin = es[i]
            while l > 0 and es[l - 1] <= es[i]:
                l -= 1
                lmin = min(lmin, es[l])
            r = i
            rmin = es[i]
            while r < n - 1 and es[r + 1] <= es[i]:
                r += 1
                rmin = min(rmin, es[r])
            if es[i] - max(lmin, rmin) >= 0.1:
                lo, hi = max(0, i - 1), min(n, i + 2)
                peaks.append(int(lo + np.argmax(raw[lo:hi])))
    return sorted(set(peaks))


def find_cycle(G, box_cells, n, fps):
    """Appearance period over the subject box: the first deep local minimum of mean |S[t+L] - S[t]|."""
    if n < 12:
        return None
    if box_cells:
        x0, y0, x1, y1 = [v * BLOCK for v in box_cells]
        S = G[:, y0:y1, x0:x1]
    else:
        S = G
    h, w = S.shape[1:]
    f = max(1, int(math.ceil(w / 32)))
    S = S[:, :h // f * f, :w // f * f]
    if S.shape[1] == 0 or S.shape[2] == 0:
        return None
    S = S.reshape(n, S.shape[1] // f, f, S.shape[2] // f, f).mean(axis=(2, 4))
    maxlag = n // 2
    if maxlag < 4:
        return None
    d = np.array([np.abs(S[L:] - S[:-L]).mean() for L in range(1, maxlag + 1)])
    d0 = float(np.median(d))
    if d0 <= 1e-4:
        return None
    best = None
    for L in range(3, maxlag):           # d index L-1 is lag L
        v = d[L - 1]
        if v < d[L - 2] and v <= d[L] and v < 0.5 * d0:
            if best is None:
                best = L
            break
    if best is None:
        return None
    # parabolic refinement of the minimum
    a, b, c = d[best - 2], d[best - 1], d[best]
    den = a - 2 * b + c
    off = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    period = best + float(np.clip(off, -0.5, 0.5))
    conf = 1 - b / d0
    return {"period_frames": round(period, 2), "period_s": round(period / fps, 3),
            "confidence": round(float(conf), 3),
            "method": "appearance autocorrelation over the subject box (first deep minimum of mean abs diff "
                      "vs lag, below half the median)"}


def region_stats(D, box, fps):
    x0, y0, x1, y1 = box
    n = D.shape[0]
    xs = np.linspace(x0, x1, 4).round().astype(int)
    ys = np.linspace(y0, y1, 4).round().astype(int)
    series = []
    for r in range(3):
        for c in range(3):
            ya, yb = ys[r], max(ys[r + 1], ys[r] + 1)
            xa, xb = xs[c], max(xs[c + 1], xs[c] + 1)
            series.append(D[:, ya:yb, xa:xb].sum(axis=(1, 2)).astype(np.float64))
    S = np.array(series)
    total = S.sum() or 1.0
    gmax = S.max() or 1.0
    cells = []
    for k in range(9):
        s = smooth(S[k], 3)
        share = float(S[k].sum() / total)
        mx = s.max()
        onset = int(np.argmax(s >= 0.5 * mx)) + 1 if mx > 0 else None
        cells.append({"cell": CELL_NAMES[k], "row": k // 3, "col": k % 3, "share": round(share, 3),
                      "peak_frame": int(np.argmax(s)) + 1 if mx > 0 else None, "onset_frame": onset,
                      "series": [round(float(v), 3) for v in S[k] / gmax]})
    active = [c for c in cells if c["share"] >= 0.05 and c["peak_frame"]]
    order = sorted(active, key=lambda c: (c["onset_frame"], c["peak_frame"]))
    lead_lag = []
    if active:
        dom = max(active, key=lambda c: c["share"])
        ds = S[CELL_NAMES.index(dom["cell"])]
        ds = ds - ds.mean()
        maxlag = max(3, int(round(fps / 4)))
        for c in order:
            s = S[CELL_NAMES.index(c["cell"])]
            s = s - s.mean()
            best, bl = -np.inf, 0
            for L in range(-maxlag, maxlag + 1):
                if L >= 0:
                    v = float(np.dot(ds[:n - L], s[L:])) if n - L > 0 else -np.inf
                else:
                    v = float(np.dot(ds[-L:], s[:n + L])) if n + L > 0 else -np.inf
                if v > best:
                    best, bl = v, L
            lead_lag.append({"cell": c["cell"], "onset_frame": c["onset_frame"], "peak_frame": c["peak_frame"],
                             "lag_vs_first_onset": c["onset_frame"] - order[0]["onset_frame"],
                             "xcorr_lag_vs_dominant": bl})
    return {"grid": "3x3 over subject_box; rows top->bottom, cols left->right; series normalised to the "
                    "largest cell value",
            "cells": cells, "first": order[0]["cell"] if order else None,
            "order": [c["cell"] for c in order], "dominant": max(active, key=lambda c: c["share"])["cell"]
            if active else None, "lead_lag": lead_lag}


def shake_ranges(dx, dy, fps):
    """Ranges with high-frequency global jitter: the shift minus its local mean flips sign and is large."""
    n = len(dx)
    if n < 5:
        return []
    k = max(3, int(round(fps / 12)) | 1)
    hx, hy = dx - smooth(dx, k), dy - smooth(dy, k)
    mag = np.hypot(hx, hy)
    mask = mag >= 1.0                          # frame px
    rr = runs(mask, 1)
    merged = []
    for a, b in rr:
        if merged and a - merged[-1][1] <= 2:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        seg = hx[a:b + 1] if np.abs(hx[a:b + 1]).sum() >= np.abs(hy[a:b + 1]).sum() else hy[a:b + 1]
        flips = int(np.sum(np.sign(seg[1:]) * np.sign(seg[:-1]) < 0))
        if b - a + 1 >= 2 and flips >= 1:
            out.append([a + 1, b + 1])
    return out


def audio_onsets(src, fps, peaks, rate=8000, trim=None):
    """Onsets from an energy-flux detector on mono PCM: 5 ms RMS hops, a rise of >= 12 dB over the previous
    50 ms minimum, 60 ms refractory."""
    try:
        info = animlib.probe(src)
    except Exception as e:
        return {"has_audio": None, "onsets": [], "peak_sync": [], "note": f"ffprobe failed: {e}"}
    if not info.get("has_audio"):
        return {"has_audio": False, "onsets": [], "peak_sync": [], "note": "no audio stream"}
    x = animlib.extract_audio(src, rate, trim=trim)
    if x is None or len(x) < rate // 20:
        return {"has_audio": True, "onsets": [], "peak_sync": [], "note": "audio stream could not be decoded"}
    hop = max(1, rate // 200)
    m = len(x) // hop
    env = np.sqrt((x[:m * hop].reshape(m, hop) ** 2).mean(axis=1))
    if env.max() < 1e-4:
        return {"has_audio": True, "onsets": [], "peak_sync": [], "note": "audio is silent"}
    db = 20 * np.log10(env + 1e-6)
    back = 10
    onsets, last = [], -10 ** 9
    for k in range(1, m):
        lo = db[max(0, k - back):k].min()
        if db[k] - lo >= 12 and env[k] >= 0.05 * env.max() and k - last >= 12:
            onsets.append(k)
            last = k
    out = []
    for k in onsets:
        t = k * hop / rate
        out.append({"ms": round(t * 1000, 1), "f": int(round(t * fps)) + 1, "f60": int(round(t * 60)) + 1})
    sync = []
    for p in peaks:
        if not out:
            break
        near = min(out, key=lambda o: abs(o["f"] - p))
        sync.append({"peak": p, "onset_f": near["f"], "offset_frames": near["f"] - p})
    return {"has_audio": True, "onsets": out, "peak_sync": sync,
            "method": "RMS envelope in 5 ms hops; onset = rise >= 12 dB over the previous 50 ms minimum, "
                      "level >= 5% of the loudest hop, 60 ms refractory; offset_frames > 0: sound after the peak"}


def mark_suspect(res, report, near=2):
    """decode_errors block: the extractor's report plus, per measured list, the items within `near` frames of a
    suspect frame (a decoder error or a dropped frame the fps filter filled with a copy)."""
    sus = sorted(set(int(f) for f in report.get("suspect_frames") or []))

    def close(f):
        return any(abs(f - s_) <= near for s_ in sus)

    def overlaps(a, b):
        return any(a - near <= s_ <= b + near for s_ in sus)

    aff = {k: [f for f in res.get(k) or [] if close(f)] for k in ("peaks", "extremes", "smears", "keypose_candidates")}
    aff["holds"] = [h for h in res.get("holds") or [] if overlaps(h[0], h[1])]
    aff["slow_segments"] = [h for h in res.get("slow_segments") or [] if overlaps(h[0], h[1])]
    aff["hitstop_candidates"] = [h for h in res.get("hitstop_candidates") or [] if overlaps(h[0], h[2])]
    out = {k: v for k, v in report.items()}
    out["suspect_frames"] = sus
    out["affected"] = {k: v for k, v in aff.items() if v}
    out["meaning"] = ("ffmpeg reported decoder errors; frames listed are corrupt or copies of a dropped frame, so "
                      "the numbers in `affected` are WEAK, not MEASURED")
    return out


# per-frame series left out of numbers_brief.json (the analyst reads the brief in one go)
SERIES_KEYS = ("energy",)


def brief(res):
    """numbers.json minus its per-frame series (camera dx/dy, energy, region series, duplicate frame list), small
    enough to read in one go. Region lead/lag order and per-region peak frames stay."""
    b = {k: v for k, v in res.items() if k not in SERIES_KEYS}
    cam = res.get("camera")
    if isinstance(cam, dict):
        b["camera"] = {k: v for k, v in cam.items() if k not in ("dx", "dy")}
    reg = res.get("regions")
    if isinstance(reg, dict):
        r2 = {k: v for k, v in reg.items() if k != "cells"}
        r2["cells"] = [{k: v for k, v in c.items() if k != "series"} for c in reg.get("cells") or []]
        b["regions"] = r2
    cap = res.get("capture")
    if isinstance(cap, dict) and "duplicate_frames" in cap:
        c2 = {k: v for k, v in cap.items() if k != "duplicate_frames"}
        dup = set(cap.get("duplicate_frames") or [])
        c2["duplicate_frames_count"] = len(dup)
        c2["duplicate_runs"] = [[a + 1, b + 1] for a, b in
                                runs([i + 1 in dup for i in range(int(res.get("frames") or 0))], 1)]
        b["capture"] = c2
    b["brief_of"] = "numbers.json (per-frame series left out: camera dx/dy, energy, region series)"
    # (critic r3) frame numbering, stated where the analyst reads first: brief frames are 1-based (f_0001 = frame 1)
    b["frame_base"] = 1
    if res.get("source") == "data":
        # a decoded .rbxm spec counts its frames from 0: spec f = brief f - 1
        b["spec_frame_offset"] = -1
        b["frame_note"] = ("frames here are 1-based (frame 1 = t 0); the decoded spec's frames are 0-based: "
                           "spec f = brief f - 1")
    elif res.get("kind") == "images":
        b["frame_note"] = "frames here are 1-based f_#### numbers in image order (stills: no time axis)"
    else:
        b["trim_offset_frames"] = int(res.get("trim_offset_frames") or 0)
        b["frame_note"] = ("frames here are 1-based f_#### numbers (f_0001 = frame 1) at fps_analysis, counted from "
                           "the trim start; source frame = f + trim_offset_frames")
    return b


def write_numbers(out_dir, res):
    """numbers.json (everything) and numbers_brief.json (no per-frame series) side by side."""
    out_dir = Path(out_dir)
    animlib.write_json(out_dir / "numbers.json", res)
    animlib.write_json(out_dir / "numbers_brief.json", brief(res))
    return out_dir / "numbers.json", out_dir / "numbers_brief.json"


def to60(f, fps):
    return int(round((f - 1) * 60.0 / fps)) + 1


# ---------------------------------------------------------------- main analysis

def analyze(frames_dir, fps, out_dir, crop=None, id=None, sheets_dir=None, fps_src=None, source=None,
            notes=None, sheets=True, trim=None, decode_errors=None):
    """Measure frames_dir (f_####.jpg/png at `fps`), write out_dir/numbers.json, numbers_brief.json and the sheets.
    trim = [start, end] seconds of the source the frames cover (recorded; audio is cut to match).
    decode_errors = extract_frames()'s report: its suspect frames mark the numbers near them. Returns the dict."""
    fps = float(fps)
    files = list_frames(frames_dir)
    if not files:
        raise RuntimeError(f"no f_####.jpg/png frames in {frames_dir}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir = Path(sheets_dir) if sheets_dir else out_dir / "sheets"
    ID = id or Path(frames_dir).resolve().parent.name or "clip"
    notes = list(notes or [])
    with Image.open(files[0]) as im0:
        FW, FH = im0.size
    if crop:
        x, y, w, h = [int(v) for v in crop]
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > FW or y + h > FH:
            raise ValueError(f"crop {crop} doesn't fit the {FW}x{FH} frames")
        crop = [x, y, w, h]
    ox, oy = (crop[0], crop[1]) if crop else (0, 0)
    G, scale = load_stack(files, crop)
    n = len(G)
    res = {"id": ID, "analyzer": VERSION, "label": MEASURED, "frame_base": 1, "trim": list(trim) if trim else None,
           "fps_src": fps_src, "fps_analysis": round(fps, 3), "frames": n, "duration_s": round(n / fps, 3),
           "crop": crop, "frame_size": [FW, FH],
           # (critic r3) f_0001 is the first frame of the trim, not of the source: source frame (at fps_analysis)
           # = f + trim_offset_frames; 0 when the whole source was analysed
           "trim_offset_frames": int(round(float(trim[0]) * fps)) if trim else 0}
    if n < 3:
        notes.append(f"only {n} frame(s): no motion can be measured")
        res.update(camera={"dx": [0.0] * n, "dy": [0.0] * n, "moving": False, "shake_candidates": []},
                   energy=[0.0] * n, regions=None, holds=[], peaks=[], extremes=[], smears=[],
                   hitstop_candidates=[], slow_segments=[], slow_detail=[], cycle=None, keypose_candidates=list(range(1, n + 1)),
                   keypose_detail=[], timing_60={}, subject_box=[ox, oy, crop[2] if crop else FW,
                                                                  crop[3] if crop else FH],
                   capture=None, audio=None, notes=notes)
        write_numbers(out_dir, res)
        if sheets:
            res["sheets"] = write_sheets(files, res, sheets_dir, ID)
        return res

    # camera
    cam, flat = estimate_camera(G, phase_shifts(G))
    # second pass: measure the camera with the moving subject masked out, so a bright subject can't pass for
    # (or hide) a camera move; skipped when the subject fills most of the frame
    D1, _, _ = comp_diffs(G, cam)
    b1 = subject_box(D1)
    if b1 is not None:
        x0, y0, x1, y1 = b1[0] * BLOCK, b1[1] * BLOCK, b1[2] * BLOCK, b1[3] * BLOCK
        h_, w_ = G.shape[1:]
        if (x1 - x0) * (y1 - y0) < 0.6 * h_ * w_:
            mk = np.ones((h_, w_), dtype=np.float32)
            mk[max(0, y0 - BLOCK):y1 + BLOCK, max(0, x0 - BLOCK):x1 + BLOCK] = 0
            mk = _feather(_feather(mk, 9), 9)   # soft edges: a hard static edge would pull the peak to zero
            cam, flat = estimate_camera(G, phase_shifts(G, mask=mk), mask=mk)
        else:
            notes.append("camera: the subject fills most of the frame; camera shift measured with it included")
    dx, dy = cam[:, 1] * scale, cam[:, 0] * scale
    if flat > 0.3 * n:
        notes.append(f"camera: the frame border is flat on {flat} of {n} frames, so camera motion there can't be "
                     f"measured (treated as static)")
    path_x, path_y = np.cumsum(dx), np.cumsum(dy)
    rng = max(np.ptp(path_x), np.ptp(path_y))
    moving_frames = int(np.sum(np.hypot(dx, dy) >= 0.75))
    moving = bool(rng >= 0.02 * (crop[2] if crop else FW) or moving_frames >= max(3, 0.1 * n))
    shakes = shake_ranges(dx, dy, fps)

    # subject energy (camera removed)
    D, raw_mean, raw_max = comp_diffs(G, cam)
    raw = D.sum(axis=(1, 2)).astype(np.float64)
    raw[0] = raw[1]
    rmax0 = raw.max() or 1.0
    capture, short_runs, step_len = capture_stats(raw_mean, raw_max, fps, raw / rmax0)
    raw2 = redistribute(raw, short_runs, step_len)
    if step_len:
        notes.append(f"stepped animation on {capture['stepping']}: each drawing's change is spread over its held "
                     f"frames before holds/peaks are found")
    es = smooth(raw2, 3)
    emax = es.max() or 1.0
    e = es / emax
    rawn = raw2 / emax
    if raw.max() <= 0:
        notes.append("no subject motion above the noise floor")

    # subject box (frame px)
    bc = subject_box(D)
    if bc is None:
        bc = [0, 0, D.shape[2], D.shape[1]]
        notes.append("subject box: no motion found; whole frame used")
    bx0, by0, bx1, by1 = [v * BLOCK * scale for v in bc]
    sbox = [int(round(ox + bx0)), int(round(oy + by0)), int(round(bx1 - bx0)), int(round(by1 - by0))]

    # holds, slow segments, peaks, extremes
    # A hold is near-zero motion relative to the clip's own noise floor (the mean of its quietest fifth of
    # frames), not merely "small next to the biggest peak": a slow wind-up a few px per frame next to a fast strike
    # is motion (it goes to slow_segments), not a hold. Measured on the unsmoothed series so hold edges stay exact.
    # the floor comes from the series before stepping is spread out: on twos, the repeated drawings are the
    # clip's true noise level (after spreading, its quietest frames are slow motion)
    body = raw[1:] if n > 1 else raw
    quiet = np.sort(body)[:max(1, len(body) // 5)]
    noise_floor = float(quiet.mean())
    rmax = float(raw2.max()) or 1.0
    thr_raw = min(max(4.0 * noise_floor, 0.004 * rmax, 0.05), 0.12 * rmax)
    thr_hold = thr_raw / emax                       # the same threshold on the normalised scale (reported)
    min_hold = max(2, int(round(fps / 20)))
    hold_mask = raw2 <= thr_raw
    # a slow drift (a wind-up's ease-in, ~1 source px a frame) can sit at the noise level frame to frame; over two
    # frames it doubles while a true hold stays flat. So a still frame must also be still across two frames,
    # looking back or forward (either side, so a hold's first and last frames keep their place).
    for i in np.nonzero(hold_mask)[0]:
        if i == 0:
            continue
        back = span_energy(G, cam, i - 2, i) if i >= 2 else None
        fwd = span_energy(G, cam, i - 1, i + 1) if i + 1 < n else None
        if not any(v is not None and v <= thr_raw for v in (back, fwd)):
            hold_mask[i] = False
    # frame 1 has no "motion into it": a hold must reach min_hold frames from frame 2 on, then it takes frame 1
    holds = [[a_ + 1, b_ + 1] for a_, b_ in runs(hold_mask[1:], min_hold)]
    if holds and holds[0][0] == 1:
        holds[0][0] = 0
    # one or two noisy frames inside a hold (a compressed clip's I/P-frame quality jumps, a sub-pixel camera
    # error) don't end it: close the gap when those frames stay under twice the threshold and the subject is
    # still in the same place across the gap
    merged = []
    for h_ in holds:
        if merged:
            a_, b_ = merged[-1]
            gap = range(b_ + 1, h_[0])
            if len(gap) <= 2 and all(raw2[g] <= 2 * thr_raw for g in gap) and                     span_energy(G, cam, b_, h_[0]) <= 2 * thr_raw:
                merged[-1] = [a_, h_[1]]
                continue
        merged.append(list(h_))
    holds = merged
    for a_, b_ in holds:
        hold_mask[a_:b_ + 1] = True
    hold_mask[0] = bool(holds and holds[0][0] == 0)
    in_hold = np.zeros(n, dtype=bool)
    for a_, b_ in holds:
        in_hold[a_:b_ + 1] = True
    # slow segments: moving, but well under the clip's fast motion (wind-ups, ease-outs, settles)
    slow_thr = 0.2
    min_slow = max(3, int(round(fps / 10)))
    slow = runs((e <= slow_thr) & ~in_hold, min_slow)
    slow_detail = [{"from": a_ + 1, "to": b_ + 1, "mean_energy": round(float(e[a_:b_ + 1].mean()), 3)}
                   for a_, b_ in slow]
    floor = max(0.2, float(np.percentile(e, 75)))
    peaks = find_peaks(e, rawn, floor)
    p60 = float(np.percentile(e, 60))
    extremes = [i for i in range(1, n - 1) if e[i] <= e[i - 1] and e[i] < e[i + 1] and e[i] < p60]

    # hit-stop: a peak, then near-zero raw motion for >= 2 frames (short: <= 0.4 s), within a few frames
    gap = max(3, int(round(fps / 15)))
    max_len = max(4, int(round(0.4 * fps)))
    low = hold_mask
    hitstops = []
    for p in peaks:
        if rawn[p] < 0.35:
            continue
        q = next((j for j in range(p + 1, min(n, p + 1 + gap)) if low[j]), None)
        if q is None:
            continue
        r = q
        while r + 1 < n and low[r + 1]:
            r += 1
        L = r - q + 1
        if 2 <= L <= max_len and r + 1 < n:
            hitstops.append([p + 1, q + 1, r + 1])

    # smears: frames blurrier than their neighbours while moving fast (Laplacian variance over the subject box)
    x0, y0, x1, y1 = [v * BLOCK for v in bc]
    sub = G[:, y0:y1, x0:x1]
    smears = []
    if sub.shape[1] > 3 and sub.shape[2] > 3:
        lap = (-4 * sub[:, 1:-1, 1:-1] + sub[:, :-2, 1:-1] + sub[:, 2:, 1:-1] + sub[:, 1:-1, :-2]
               + sub[:, 1:-1, 2:])
        sharp = lap.reshape(n, -1).var(axis=1)
        sm = smooth(sharp, 5)
        smears = [i for i in range(n) if sharp[i] < 0.6 * sm[i] and e[i] > p60]

    # cycle, regions
    cycle = find_cycle(G, bc, n, fps)
    if moving and cycle is None:
        notes.append("cycle: measured in frame coordinates; a moving camera can hide a loop")
    regions = region_stats(D, bc, fps)

    # key-pose candidates: ends, hold edges, extremes, peaks; thinned to >= 2 frames apart
    rank = {}
    for a, b in holds:
        rank[a] = rank[b] = 3
    for a_, b_ in slow:
        rank[a_] = max(rank.get(a_, 0), 2.2)     # where a wind-up / settle starts and ends
        rank[b_] = max(rank.get(b_, 0), 2.2)
    for i in extremes:
        rank[i] = max(rank.get(i, 0), 2)
    for i in peaks:
        rank[i] = max(rank.get(i, 0), 1)
    for p_, _q, _r in hitstops:
        rank[p_ - 1] = 3.5                 # the contact pose; the frozen frame after it shows the same pose
    rank[0] = rank[n - 1] = 4
    thinned = []
    for k in sorted(rank):
        if thinned and k - thinned[-1] < 2:
            if rank[k] > rank[thinned[-1]]:
                thinned[-1] = k
            continue
        thinned.append(k)
    kind = {4: "end", 3.5: "contact", 3: "hold", 2.2: "slow", 2: "extreme", 1: "fast"}
    detail = [{"frame": k + 1, "type": ("start" if k == 0 else kind[rank[k]]), "energy": round(float(e[k]), 3)}
              for k in thinned]

    audio = None
    if source:
        audio = audio_onsets(source, fps, [p + 1 for p in peaks], trim=trim)
        if audio.get("note"):
            notes.append("audio: " + audio["note"])
    else:
        notes.append("audio: no source clip given; not measured")

    one = lambda xs: [int(i) + 1 for i in xs]  # noqa: E731
    res.update({
        "camera": {"dx": [round(float(v), 2) for v in dx], "dy": [round(float(v), 2) for v in dy],
                   "path_range_px": round(float(rng), 1), "moving": moving, "moving_frames": moving_frames,
                   "shake_candidates": shakes,
                   "method": "content shift frame i-1 -> i in frame px (phase correlation, Hann window, sub-pixel "
                             "peak), kept only when it explains the frame border; content moves opposite to the "
                             "camera"},
        "energy": [round(float(v), 4) for v in e],
        "regions": regions,
        "holds": [[a + 1, b + 1] for a, b in holds],
        "slow_segments": [[a + 1, b + 1] for a, b in slow],
        "slow_detail": slow_detail,
        "peaks": one(peaks),
        "extremes": one(extremes),
        "smears": one(smears),
        "hitstop_candidates": hitstops,
        "cycle": cycle,
        "keypose_candidates": [d["frame"] for d in detail],
        "keypose_detail": detail,
        "subject_box": sbox,
        "capture": capture,
        "audio": audio,
        "thresholds": {"hold": round(float(thr_hold), 4), "hold_raw": round(thr_raw, 3),
                       "noise_floor_raw": round(noise_floor, 3), "slow": slow_thr, "peak_floor": round(floor, 3),
                       "min_hold_frames": min_hold, "min_slow_frames": min_slow,
                       "method": "hold = unsmoothed compensated motion <= max(4 x noise floor, 0.4% of the "
                                 "largest frame) (capped at 12%), also across two frames (back or forward); "
                                 "slow = smoothed energy <= 0.2 outside holds"},
    })
    res["timing_60"] = {
        "holds": [[to60(a, fps), to60(b, fps)] for a, b in res["holds"]],
        "slow_segments": [[to60(a, fps), to60(b, fps)] for a, b in res["slow_segments"]],
        "peaks": [to60(f, fps) for f in res["peaks"]],
        "extremes": [to60(f, fps) for f in res["extremes"]],
        "smears": [to60(f, fps) for f in res["smears"]],
        "hitstop_candidates": [[to60(f, fps) for f in h] for h in hitstops],
        "shake_candidates": [[to60(a, fps), to60(b, fps)] for a, b in shakes],
        "keypose_candidates": [to60(f, fps) for f in res["keypose_candidates"]],
        "cycle_period_frames": round(cycle["period_frames"] * 60.0 / fps, 2) if cycle else None,
        "frames": int(round(n * 60.0 / fps)),
        # these 60 fps frames count from the trim like f_####; source frame at 60 = f60 + trim_offset_frames_60
        "trim_offset_frames_60": int(round(float(trim[0]) * 60.0)) if trim else 0,
    }
    if decode_errors and decode_errors.get("events"):
        res["decode_errors"] = mark_suspect(res, decode_errors)
    res["notes"] = notes
    if sheets:
        res["sheets"] = write_sheets(files, res, sheets_dir, ID)
    write_numbers(out_dir, res)
    return res


# ---------------------------------------------------------------- sheets

def _crop_box(res, pad=0.12):
    x, y, w, h = res["subject_box"]
    FW, FH = res["frame_size"]
    px, py = int(w * pad), int(h * pad)
    return (max(0, x - px), max(0, y - py), min(FW, x + w + px), min(FH, y + h + py))


def write_sheets(files, res, sheets_dir, ID):
    sheets_dir = Path(sheets_dir)
    sheets_dir.mkdir(parents=True, exist_ok=True)
    n = len(files)
    fps = res["fps_analysis"]
    out = {}
    # contact 4x4
    idx = sorted({int(round(i * (n - 1) / 15)) for i in range(16)}) if n > 16 else list(range(n))
    out["contact"] = str(animlib.sheet([(files[i], f"f{i + 1}  {i / fps:.2f}s") for i in idx],
                                       sheets_dir / f"{ID}_contact.jpg", cols=4,
                                       title=f"{ID}  {n} frames @ {fps:g} fps"))
    box = _crop_box(res)

    def crop(i):
        with Image.open(files[i]) as im:
            return im.convert("RGB").crop(box)

    detail = res.get("keypose_detail") or [{"frame": f, "type": ""} for f in res["keypose_candidates"]]
    kp = detail[:24]
    out["keyposes"] = str(animlib.sheet([(crop(d["frame"] - 1), f"f{d['frame']} {d['type']}") for d in kp],
                                        sheets_dir / f"{ID}_keyposes.jpg", cols=6, tile_w=240,
                                        title=f"{ID} key-pose candidates (subject box)"))
    # strips: +-3 around the biggest peaks
    peaks = res.get("peaks") or []
    en = res.get("energy") or [0] * n
    big = sorted(sorted(peaks, key=lambda f: -en[f - 1])[:4]) or [int(np.argmax(en)) + 1]
    tiles = []
    blank = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (18, 18, 20))
    for p in big:
        for k in range(-3, 4):
            f = p + k
            if 1 <= f <= n:
                tiles.append((crop(f - 1), f"f{f}" + ("  PEAK" if k == 0 else "")))
            else:
                tiles.append((blank, ""))
    out["strips"] = str(animlib.sheet(tiles, sheets_dir / f"{ID}_strips.jpg", cols=7, tile_w=200,
                                      title=f"{ID} dense strips: every frame +-3 around peaks {big}"))
    # onion: key poses ghosted over the median background
    ks = [d["frame"] for d in detail if d["type"] != "fast"][:10]
    if len(ks) < 3:
        ks = sorted({int(round(i * (n - 1) / 7)) + 1 for i in range(8)})
    stack = np.stack([np.asarray(crop(f - 1), dtype=np.float32) for f in ks])
    bg = np.median(stack, axis=0)
    ghost = bg + (stack.mean(axis=0) - bg) * min(4.0, len(stack))
    onion = Image.fromarray(np.clip(ghost, 0, 255).astype(np.uint8))
    onion = animlib.fit(onion, 960, 960) if max(onion.size) > 960 else onion
    if onion.width < 640:
        # (critic r3) a small subject box made an unreadable thumbnail: scale it up to 640 px wide
        k = 640.0 / onion.width
        onion = onion.resize((640, max(1, int(round(onion.height * k)))), Image.LANCZOS)
    animlib.save_image(onion, sheets_dir / f"{ID}_onion.jpg")
    out["onion"] = str(sheets_dir / f"{ID}_onion.jpg")
    out["motion"] = str(motion_plot(res, sheets_dir / f"{ID}_motion.png"))
    return out


def motion_plot(res, path):
    n = res["frames"]
    e = np.array(res["energy"], dtype=float)
    W, pad = 1400, 50
    H1, H2, H3 = 260, 140, 9 * 16
    H = 30 + H1 + 30 + H2 + 30 + H3 + 40
    im = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(im)
    f = animlib.font(12)
    X = lambda i: pad + (W - 2 * pad) * i / max(n - 1, 1)  # noqa: E731
    top1 = 30
    Y = lambda v: top1 + H1 - H1 * v  # noqa: E731
    d.text((pad, 8), f"{res['id']}  subject energy (camera removed). blue = hold, purple = hit-stop, red = peak, "
                     f"orange = smear, green tick = key pose", fill=(0, 0, 0), font=f)
    for a, b in res["holds"]:
        d.rectangle([X(a - 1), top1, X(b - 1), top1 + H1], fill=(220, 235, 255))
    for p, a, b in res["hitstop_candidates"]:
        d.rectangle([X(a - 1), top1, X(b - 1), top1 + H1], fill=(230, 210, 245))
    for s in res["smears"]:
        d.line([X(s - 1), top1, X(s - 1), top1 + H1], fill=(255, 190, 110))
    if n > 1:
        d.line([(X(i), Y(v)) for i, v in enumerate(e)], fill=(30, 30, 30), width=2)
    for p in res["peaks"]:
        d.ellipse([X(p - 1) - 4, Y(e[p - 1]) - 4, X(p - 1) + 4, Y(e[p - 1]) + 4], fill=(220, 40, 40))
        d.text((X(p - 1) - 6, top1 - 14), str(p), fill=(220, 40, 40), font=f)
    for k in res["keypose_candidates"]:
        d.line([X(k - 1), top1 + H1, X(k - 1), top1 + H1 + 6], fill=(40, 150, 60), width=2)
    step = max(1, int(round(n / 20)))
    for i in range(0, n, step):
        d.text((X(i) - 6, top1 + H1 + 8), str(i + 1), fill=(90, 90, 90), font=f)
    # camera
    top2 = top1 + H1 + 30
    dx = np.array(res["camera"]["dx"], dtype=float)
    dy = np.array(res["camera"]["dy"], dtype=float)
    m = max(1.0, float(np.abs(np.concatenate([dx, dy])).max()) if n else 1.0)
    d.text((pad, top2 - 2), f"camera content shift per frame (px; +-{m:.1f}); dark = dx, light = dy; "
                            f"moving={res['camera']['moving']}", fill=(0, 0, 0), font=f)
    mid = top2 + 14 + (H2 - 14) / 2
    d.line([pad, mid, W - pad, mid], fill=(200, 200, 200))
    for a, b in res["camera"]["shake_candidates"]:
        d.rectangle([X(a - 1), top2 + 14, X(b - 1), top2 + H2], outline=(220, 120, 40))
    for arr, col in ((dy, (150, 150, 220)), (dx, (40, 40, 140))):
        if n > 1:
            d.line([(X(i), mid - (H2 - 14) / 2 * v / m) for i, v in enumerate(arr)], fill=col, width=2)
    # regions heat map
    top3 = top2 + H2 + 30
    d.text((pad, top3 - 16), "3x3 region energy over the subject box (rows top-left .. bottom-right)",
           fill=(0, 0, 0), font=f)
    reg = res.get("regions") or {}
    cells = reg.get("cells") or []
    colw = (W - 2 * pad) / max(n, 1)
    for r, c in enumerate(cells):
        s = c["series"]
        y = top3 + r * 16
        for i, v in enumerate(s):
            g = int(255 - 220 * min(1.0, v))
            d.rectangle([pad + i * colw, y, pad + (i + 1) * colw, y + 14], fill=(255, g, g))
        d.text((4, y), c["cell"][:12], fill=(0, 0, 0), font=animlib.font(10))
    im.save(path)
    return path


# ---------------------------------------------------------------- CLI

def _parse_crop(s):
    v = [int(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("--crop wants x,y,w,h in frame pixels")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure motion in extracted frames (anim_analyze v2).")
    ap.add_argument("frames_dir")
    ap.add_argument("--fps", type=float, required=True, help="the frames' rate (analysis fps)")
    ap.add_argument("--out", required=True, help="writes numbers.json here and sheets in <out>/sheets")
    ap.add_argument("--id", default=None)
    ap.add_argument("--crop", type=_parse_crop, default=None, help="x,y,w,h in frame pixels")
    ap.add_argument("--source", default=None, help="the source clip, for audio onsets")
    ap.add_argument("--fps-src", type=float, default=None)
    ap.add_argument("--trim", default=None, help="start-end seconds the frames cover (recorded; audio cut to match)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    res = analyze(a.frames_dir, a.fps, a.out, crop=a.crop, id=a.id, fps_src=a.fps_src, source=a.source,
                  trim=animlib.parse_trim(a.trim) if a.trim else None)
    if a.json:
        print(json.dumps({k: v for k, v in res.items() if k not in ("energy", "regions", "camera")}, indent=1))
    else:
        print(f"{res['frames']} frames @ {res['fps_analysis']:g}: peaks {res['peaks']}  holds {res['holds']}  "
              f"hit-stop {res['hitstop_candidates']}  camera moving={res['camera']['moving']}  cycle {res['cycle']}")
        print(f"wrote {Path(a.out) / 'numbers.json'} and sheets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
