"""Life pass for AnimSpecs: no part is ever stationary (the `--life` polish lever).

Three layers on top of the authored motion, then re-keyed with "flow" easing:
  1. SWAY — every part gets a small elliptical sway in its local axes: x and z run 90 deg out of phase, so the
     rotation never comes to rest (a 1-axis sine stops at every extreme; an ellipse has ~constant speed).
     Loops use whole-number cycles per loop so the seam stays closed. Hinge parts (forearm, shin) sway on
     bend + twist (pronation / tibial twist), never sideways.
  2. DRAG — children lag behind their parent's angular acceleration through a damped spring (follow-through /
     overlapping action): fast torso twists whip the head, arms, forearms and hands. Hinges are masked to their
     real axes; elbows/knees are clamped so they never hyper-extend.
  3. HIP SWAY COMPENSATION — the upper legs counter-rotate the hips' sway, so planted feet stay planted while the
     pelvis still moves.
Re-keying: the composite is sampled every frame, keys start at the authored key frames + sway extrema and are added
where the reconstruction (with the pipeline's own easing evaluator) misses by > tol. Easing per segment is chosen
from the motion ("flow"): CubicV2 InOut only where the direction reverses, In/Out at one-sided reversals, Linear
where motion continues through the key -> no InOut stall at every key.

Usage:  python kit/scripts/anim_spec.py polish v.json -o v_next.json --life 1.0[:1.0]   (sway amp : drag gain)
        or import anim_life; anim_life.apply(spec, amp=1.0, drag=1.0)
"""
from __future__ import annotations

import math
import zlib

import anim_rig as R
import anim_spec as A

# (name match, class) — first match wins
CLASSES = [("LowerTorso", "hips"), ("UpperTorso", "chest"), ("Torso", "chest"), ("Head", "head"),
           ("UpperArm", "arm"), ("LowerArm", "forearm"), ("Hand", "hand"),
           ("UpperLeg", "thigh"), ("LowerLeg", "shin"), ("Foot", "foot"), ("Arm", "arm"), ("Leg", "thigh")]
# sway amplitude in degrees about local x / y / z (x,z elliptical; y slower)
AMP = {"hips": (0.9, 0.7, 0.9), "chest": (1.2, 1.0, 1.0), "head": (2.0, 2.4, 1.4), "arm": (2.2, 1.2, 2.4),
       "forearm": (2.6, 2.2, 0.0), "hand": (4.0, 2.0, 3.0), "thigh": (0.0, 0.0, 0.0), "shin": (1.3, 1.0, 0.0),
       "foot": (1.8, 0.0, 1.3)}
DRAG = {"hips": 0.0, "chest": 0.12, "head": 0.30, "arm": 0.22, "forearm": 0.30, "hand": 0.40, "thigh": 0.0,
        "shin": 0.05, "foot": 0.06}
MASK = {"forearm": (1, 0.5, 0), "shin": (1, 0.3, 0), "foot": (1, 0, 0.5), "hand": (1, 0.5, 1)}
HINGE = {"forearm": (2.0, 170.0), "shin": (-170.0, -1.0)}  # allowed rx range (elbow bends +, knee bends -)
MIN_SPEED = 4.5  # deg/s: sway speed floor — high enough that authored drift can never cancel it to a stop
SPRING_PERIOD_S, SPRING_ZETA, DRAG_CLAMP = 0.33, 0.4, 15.0


def klass(part):
    for key, c in CLASSES:
        if key in part:
            return c
    return "chest"


def _phase(part, salt):
    return (zlib.crc32(f"{part}:{salt}".encode()) % 10000) / 10000 * 2 * math.pi


def _vec(v, s):
    return [x * s for x in v]


def _add(a, b):
    return [x + y for x, y in zip(a, b)]


def _mt(m, v):  # transpose(m) * v
    return [sum(m[k][i] * v[k] for k in range(3)) for i in range(3)]


def _mv(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def apply(spec, amp=1.0, drag=1.0, period_s=1.8, tol=0.5, tol_p=0.015, key_cap=0.4):
    fps = spec.get("fps", 60)
    L = A.length(spec)
    loop = bool(spec.get("loop"))
    rig = A.rig_of(spec)
    parts = [p for p in rig["parts"]]
    T = spec["tracks"]
    nF = int(math.floor(L + 1e-9))
    F_int = list(range(0, nF + 1))
    key_frames = {p: sorted({k["f"] for k in T.get(p, [])} | {0, L}) for p in parts}
    F_all = {p: sorted(set(F_int) | set(key_frames[p]) | {L}) for p in parts}

    # ---- base (authored) rel + world rotation per frame (integer frames; fractional via eval)
    def base(p, f):
        return A.eval_track(spec, T.get(p, []), f)

    order = []  # parents before children
    seen = {rig["root"]}
    while len(order) < len(parts):
        for p in parts:
            if p not in seen and rig["parts"][p]["parent"] in seen:
                order.append(p)
                seen.add(p)
    W = {}  # (part, frame) -> world rotation
    for f in F_int:
        for p in order:
            par = rig["parts"][p]["parent"]
            pw = W.get((par, f), R.IDENTITY)
            W[(p, f)] = R.mat_mul(pw, base(p, f)[0])

    # ---- DRAG: damped spring on each part, driven by its parent's world angular acceleration
    k = (2 * math.pi / (SPRING_PERIOD_S * fps)) ** 2
    c = 2 * SPRING_ZETA * math.sqrt(k)
    dragvec = {}
    period = nF if loop else None
    for p in parts:
        g = DRAG[klass(p)] * drag
        par = rig["parts"][p]["parent"]
        if g <= 0 or par == rig["root"]:
            continue

        def omega(f):  # parent's world angular velocity (deg/frame, world axes) arriving at frame f
            if f == 0 and not loop:
                return [0.0, 0.0, 0.0]
            f0 = (f - 1) % period if loop else f - 1
            a, b = W[(par, f0)], W[(par, f)]
            return _vec(R.mat_log(R.mat_mul(b, R.mat_t(a))), 180 / math.pi)

        om = [omega(f) for f in range(nF if loop else nF + 1)]
        s, v = [0.0] * 3, [0.0] * 3
        out = {}
        passes = 4 if loop else 1
        n = len(om)
        for it in range(passes):
            for i in range(n):
                acc = [om[i][j] - om[i - 1][j] if (i > 0 or loop) else 0.0 for j in range(3)]
                v = [v[j] + (-k * s[j] - c * v[j] - g * acc[j]) for j in range(3)]
                s = [s[j] + v[j] for j in range(3)]
                mag = math.sqrt(sum(x * x for x in s))
                if mag > DRAG_CLAMP:
                    s = _vec(s, DRAG_CLAMP / mag)
                if it == passes - 1:
                    out[i] = s[:]
        if loop:
            out[nF] = out[0]
        dragvec[p] = out

    # ---- SWAY: elliptical, per part phase; whole cycles per loop
    # (thighs have no own sway: they move relative to the hips through the hip-sway compensation, which keeps the
    #  feet planted — an own sway could cancel it and freeze the thigh)
    def rates(p):
        if loop:
            n = max(1, round(L / (period_s * fps)))
            n += zlib.crc32(p.encode()) % 2  # neighbours get different rates
            return 2 * math.pi * n / L, 2 * math.pi * (n + 1) / L
        jit = 0.8 + 0.45 * ((zlib.crc32(p.encode()) % 1000) / 1000)
        w = 2 * math.pi / (period_s * fps * jit)
        return w, w * 0.62

    boost = {p: 1.0 for p in parts}  # raised by the repair loop for parts that still stall

    def amps(p):
        ax, ay, az = AMP[klass(p)]
        w, _ = rates(p)
        floor_amp = MIN_SPEED / (w * fps)  # deg such that A * w * fps >= MIN_SPEED (deg/s)
        b = boost[p]
        return ((max(ax * amp, floor_amp) * b) if ax else 0.0, ay * amp * b,
                (max(az * amp, floor_amp) * b) if az else 0.0, floor_amp * b)

    def sway(p, f):
        if not any(AMP[klass(p)]):
            return [0.0, 0.0, 0.0]
        w, wy = rates(p)
        ax2, ay2, az2, floor_amp = amps(p)
        ph = _phase(p, "xz")
        if not az2:  # hinge: pair x with y (twist) in quadrature instead of z
            return [ax2 * math.sin(w * f + ph), max(ay2, floor_amp) * math.cos(w * f + ph), 0.0]
        return [ax2 * math.sin(w * f + ph), ay2 * math.sin(wy * f + _phase(p, "y")), az2 * math.cos(w * f + ph)]

    def drag_at(p, f):
        d = dragvec.get(p)
        if not d:
            return [0.0] * 3
        f0 = int(math.floor(f))
        t = f - f0
        a = d.get(f0, d.get(min(d), [0.0] * 3))
        b = d.get(f0 + 1, a)
        return [x + (y - x) * t for x, y in zip(a, b)]

    def world_at(p, f):
        if (p, f) in W:
            return W[(p, f)]
        par = rig["parts"][p]["parent"]
        pw = R.IDENTITY if par == rig["root"] else world_at(par, f)
        return R.mat_mul(pw, base(p, f)[0])

    hips = next((p for p in parts if klass(p) == "hips"), None)

    def target(p, f):
        rel, off = base(p, f)
        cls = klass(p)
        loc = [x * math.pi / 180 for x in sway(p, f)]
        d = drag_at(p, f)
        if any(d):
            dl = _mt(world_at(p, f), d)  # world drag -> part-local
            m = MASK.get(cls, (1, 1, 1))
            loc = _add(loc, [dl[i] * m[i] * math.pi / 180 for i in range(3)])
        out = R.mat_mul(rel, R.mat_exp(loc))
        if cls == "thigh" and hips and rig["parts"][p]["parent"] == hips:
            q = R.mat_exp([x * math.pi / 180 for x in sway(hips, f)])  # hips sway Q -> thigh pre-multiplied by Q^T
            out = R.mat_mul(R.mat_t(q), out)
        if cls in HINGE:
            e = R.mat_to_euler(out)
            lo, hi = HINGE[cls]
            # near-straight hinge: bend just enough that the whole sway fits (never clip the sway flat)
            room = amps(p)[0] + 1.0
            b = R.mat_to_euler(rel)[0]
            if lo > -90 and b < lo + room:
                e[0] += lo + room - b
                out = R.euler_to_mat(e)
            if hi < 90 and b > hi - room:
                e[0] -= b - (hi - room)
                out = R.euler_to_mat(e)
            if not lo <= e[0] <= hi:
                e[0] = min(hi, max(lo, e[0]))
                out = R.euler_to_mat(e)
        return out, off

    # ---- re-key each part with flow easing
    def build(p):
        tgt = {f: target(p, f) for f in F_all[p]}
        if loop:
            tgt[L] = tgt[0]
        keys = set(key_frames[p])  # authored keys stay; refinement adds the worst-fit frames until within tol
        # + a key every quarter sway period, so consecutive keys never sit on opposite sides of the sway ellipse
        # (that reads as a reversal -> InOut -> a stall). Thighs follow the hips' rate.
        src = hips if (klass(p) == "thigh" and hips) else p
        if any(AMP[klass(src)]):
            q = (2 * math.pi / rates(src)[0]) / 4
            g = q
            while g < L - 1:
                if min(abs(g - kf) for kf in keys) > 1.5:
                    keys.add(round(g))
                g += q
        cap = max(len(key_frames[p]) + 2, int(key_cap * (L + 1)))
        while True:
            klist = _flow_keys(sorted(keys), tgt, loop)
            worst, wf = 0.0, None
            for f in F_all[p]:
                if f in keys:
                    continue
                rr, oo = A.eval_track(spec, klist, f)
                err = R.angle_between(rr, tgt[f][0]) + math.dist(oo, tgt[f][1]) * (tol / tol_p)
                if err > worst:
                    worst, wf = err, f
            if worst <= tol or wf is None or len(keys) >= cap:
                break
            keys.add(wf)
        return _flow_keys(sorted(keys), tgt, loop)

    new_tracks = {p: build(p) for p in parts}
    # ---- repair: any part still frozen >= 100 ms (authored motion cancelling the sway) gets 1.5x sway, rebuilt
    thighs = {p for p in parts if klass(p) == "thigh"}
    repaired = []
    for _ in range(3):
        spec["tracks"] = new_tracks
        bad = [p for p, (ms, _t) in motion_report(spec).items() if ms >= 100]
        if not bad:
            break
        for p in bad:
            boost[p] *= 1.5
        repaired += bad
        for p in set(bad) | (thighs if hips in bad else set()):
            new_tracks[p] = build(p)
    spec["tracks"] = new_tracks
    if repaired:
        spec["history"].append("life repair: sway x1.5 on " + ", ".join(sorted(set(repaired))))
    spec.setdefault("history", []).append(
        f"life pass (anim_life): elliptical sway amp {amp} + drag {drag} + hip-sway leg compensation, flow easing, tol {tol} deg")
    return spec


def _dir(a, b):
    """Motion direction from key value a to b: rotation vector (deg) + offset (scaled)."""
    v = _vec(R.mat_log(R.mat_mul(b[0], R.mat_t(a[0]))), 180 / math.pi)
    return v + [x * 30 for x in (b[1][i] - a[1][i] for i in range(3))]


def _flow_keys(frames, tgt, loop):
    vals = [tgt[f] for f in frames]
    n = len(vals)
    dirs = [_dir(vals[i], vals[i + 1]) for i in range(n - 1)]

    def reversal(i):
        if i == 0 or i == n - 1:
            if not loop or n < 3:
                return True
            a, b = dirs[-1], dirs[0]
        else:
            a, b = dirs[i - 1], dirs[i]
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        if na < 0.05 or nb < 0.05:
            return True
        # reversal = direction turns > ~100 deg; a 90 deg turn (elliptical sway keyed at quarter points) flows through
        return sum(x * y for x, y in zip(a, b)) / (na * nb) < -0.2

    rev = [reversal(i) for i in range(n)]
    out = []
    for i, f in enumerate(frames):
        if i < n - 1:
            e, d = {(True, True): ("CubicV2", "InOut"), (True, False): ("CubicV2", "In"),
                    (False, True): ("CubicV2", "Out"), (False, False): ("Linear", "InOut")}[(rev[i], rev[i + 1])]
        else:
            e, d = "CubicV2", "InOut"
        out.append(dict(A.mkkey(f, vals[i][0], vals[i][1], e, d), fl=1))
    return out


def motion_report(spec, still_dps=1.5, still_px=0.05, hz=60, frozen_ms=100, frozen_out=None):
    """Per part: longest stretch (ms) where the part is visibly frozen — slower than still_dps (deg/s) BOTH in the world
    (riding a moving parent counts as moving) AND relative to its parent (articulating under a still body counts as
    moving), with root offsets slower than still_px (studs/s). Parts without a track only move if their parent moves.
    Returns {part: (longest_ms, still_ms_total)}. If frozen_out is a list, it receives one entry per sample (n+1) listing
    the parts that are inside a still run of >= frozen_ms at that sample (for the preview timeline)."""
    rig = A.rig_of(spec)
    fps = spec.get("fps", 60)
    L = A.length(spec)
    step = fps / hz
    n = int(round(L / step))
    parts = list(rig["parts"])
    order, seen = [], {rig["root"]}
    while len(order) < len(parts):
        for p in parts:
            if p not in seen and rig["parts"][p]["parent"] in seen:
                order.append(p)
                seen.add(p)

    def pose(f):
        rel, world = {}, {}
        for p in order:
            r, o = A.eval_track(spec, spec["tracks"].get(p, []), f)
            par = rig["parts"][p]["parent"]
            rel[p] = (r, o)
            world[p] = R.mat_mul(world.get(par, R.IDENTITY), r)
        return rel, world

    run = {p: 0 for p in parts}
    longest = {p: 0 for p in parts}
    total = {p: 0 for p in parts}
    need = max(1, math.ceil(frozen_ms * hz / 1000))
    frozen = [[] for _ in range(n + 1)]
    prev = pose(0)
    for i in range(1, n + 1):
        cur = pose(i * step)
        for p in parts:
            rs = R.angle_between(prev[0][p][0], cur[0][p][0]) * hz
            ws = R.angle_between(prev[1][p], cur[1][p]) * hz
            ps = math.dist(prev[0][p][1], cur[0][p][1]) * hz
            if rs < still_dps and ws < still_dps and ps < still_px:
                run[p] += 1
                total[p] += 1
                longest[p] = max(longest[p], run[p])
                if run[p] >= need:  # mark the whole run once it qualifies
                    for j in range(i - run[p], i + 1):
                        if p not in frozen[j]:
                            frozen[j].append(p)
            else:
                run[p] = 0
        prev = cur
    if frozen_out is not None:
        frozen_out.extend(frozen)
    return {p: (round(longest[p] * 1000 / hz), round(total[p] * 1000 / hz)) for p in parts}
