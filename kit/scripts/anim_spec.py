"""AnimSpec tool — author, lint, improve, retarget and build Roblox animations from JSON.

The AnimSpec is the single source of truth for every recreation attempt
(<specs dir>/<ASSET-ID>/<ASSET-ID>_v###.json). Format & rules: knowledge/spec-format.md.

Commands (the spec argument is just a file path):
  python kit/scripts/anim_spec.py new      <out.json> --id ANIM-COMBAT-0001 --rig R6 --fps 60 --length 40
  python kit/scripts/anim_spec.py lint     <spec.json>                       # automated polish critique
  python kit/scripts/anim_spec.py retarget <spec.json> --to R15 -o <out.json> [--waist-split 0.5 --elbow 8 --knee 0]
  python kit/scripts/anim_spec.py polish   <spec.json> -o <out.json> [--overlap "Right Arm:1,Head:2"]
          [--overshoot "Right Arm@18:0.15:3"] [--exaggerate "Right Arm:10-22:1.25"] [--retime "0-12:0.75"]
          [--ease "Right Arm@12:Linear:In"] [--mirror] [--life 1.0[:1.0]]
  python kit/scripts/anim_spec.py build    <spec.json> --luau <out.luau> [--rbxmx <out.rbxmx>] [--bake N]
  python kit/scripts/anim_spec.py pose     <spec.json> --frame 18 --luau <out.luau>   # static pose snapshot
  python kit/scripts/anim_spec.py chart    <spec.json> --png <out.png> [--md]
  python kit/scripts/anim_spec.py import   <studio_dump.json> -o <spec.json> --id ANIM-...  # KeyframeSequence -> spec
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_rig as R  # noqa: E402

STYLES = ["Linear", "Constant", "Elastic", "Cubic", "Bounce", "CubicV2"]  # Enum.PoseEasingStyle 0..5
DIRS = ["In", "Out", "InOut"]                                             # Enum.PoseEasingDirection 0..2
PRIORITY = {"Idle": 0, "Movement": 1, "Action": 2, "Action2": 3, "Action3": 4, "Action4": 5, "Core": 1000}
MIRROR = {"Right Arm": "Left Arm", "Right Leg": "Left Leg"}
for _s in ("UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot"):
    MIRROR["Right" + _s] = "Left" + _s
MIRROR.update({v: k for k, v in list(MIRROR.items())})
EXTREMITIES = {"Head", "Right Arm", "Left Arm", "RightUpperArm", "LeftUpperArm", "RightLowerArm", "LeftLowerArm",
               "RightHand", "LeftHand", "Handle"}
TORSO = {"Torso", "LowerTorso", "UpperTorso"}

# ------------------------------------------------------------------ easing

def _bounce_out(t):
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def _elastic_out(t):
    if t in (0, 1):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


def ease(style: str, direction: str, t: float) -> float:
    """Approximation of Roblox pose easing (value from this key toward the next).
    Legacy 'Cubic' is treated as CubicV2 with In/Out swapped (the documented direction bug) — verify."""
    t = max(0.0, min(1.0, t))
    if style == "Constant":
        return 0.0
    if style == "Linear":
        return t
    if style == "Cubic":
        style, direction = "CubicV2", {"In": "Out", "Out": "In"}.get(direction, direction)
    out = {"CubicV2": lambda x: 1 - (1 - x) ** 3, "Elastic": _elastic_out, "Bounce": _bounce_out}[style]
    if direction == "Out":
        return out(t)
    if direction == "In":
        return 1 - out(1 - t)
    return (1 - out(1 - 2 * t)) / 2 if t < 0.5 else (1 + out(2 * t - 1)) / 2


# ------------------------------------------------------------------ spec helpers

def load(path):
    return json.load(open(path, encoding="utf-8"))


def save(spec, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    for part, keys in spec["tracks"].items():
        keys.sort(key=lambda k: k["f"])
    json.dump(spec, open(path, "w", encoding="utf-8"), indent=1)
    print(f"wrote {path}")


def rig_of(spec, rig_file=None):
    rig = R.load_rig(spec["rig"], rig_file or spec.get("rig_file"))
    return R.add_extra_joints(rig, spec.get("extra_joints"))


def key_rot(k):
    return R.euler_to_mat(k.get("r", [0, 0, 0]))


def key_off(k):
    return list(k.get("p", [0, 0, 0]))


def length(spec):
    last = max((k["f"] for keys in spec["tracks"].values() for k in keys), default=0)
    return max(spec.get("length", 0), last)


def eval_track(spec, keys, f):
    """(rotation matrix, offset) of one part at frame f (float allowed).
    Roblox does NOT interpolate last->first on looped clips, so neither do we: loops must end on a copy of
    the first pose (lint checks it; polish --overlap re-closes the seam automatically)."""
    if not keys:
        return R.IDENTITY, [0, 0, 0]
    keys = sorted(keys, key=lambda k: k["f"])
    if f <= keys[0]["f"]:
        return key_rot(keys[0]), key_off(keys[0])
    if f >= keys[-1]["f"]:
        return key_rot(keys[-1]), key_off(keys[-1])
    for a, b in zip(keys, keys[1:]):
        if a["f"] <= f < b["f"]:
            return _interp(a, b, (f - a["f"]) / (b["f"] - a["f"]))
    return key_rot(keys[-1]), key_off(keys[-1])


def _interp(a, b, t):
    e = ease(a.get("e", "CubicV2"), a.get("d", "InOut"), t)
    return R.slerp_mat(key_rot(a), key_rot(b), e), R.lerp_vec(key_off(a), key_off(b), e)


def mkkey(f, rot, off, e="CubicV2", d="InOut"):
    k = {"f": round(f, 3), "r": R.mat_to_euler(rot), "e": e, "d": d}
    if any(abs(x) > 1e-5 for x in off):
        k["p"] = [round(x, 4) for x in off]
    return k


def all_frames(spec):
    return sorted({k["f"] for keys in spec["tracks"].values() for k in keys})


# ------------------------------------------------------------------ retarget R6 -> R15

def retarget(spec, to="R15", waist_split=0.5, elbow=8.0, knee=0.0, wrist=0.0, densify=0):
    """densify=N adds Linear in-between keys every N frames on composed tracks (legs) so they match the R6 motion between keys."""
    if spec["rig"].upper() == to.upper():
        return copy.deepcopy(spec)
    if not (spec["rig"].upper() == "R6" and to.upper() == "R15"):
        raise SystemExit("only R6 -> R15 retargeting is implemented (R15 -> R6 loses elbows/knees; do it by hand)")
    T = spec["tracks"]
    out = copy.deepcopy(spec)
    out["rig"], out["tracks"] = "R15", {}
    out["version"] = int(spec.get("version", 1)) + 1  # every change is a new version (pipeline Stage 4)
    out.setdefault("history", []).append(f"retarget R6->R15 waist_split={waist_split} elbow={elbow} knee={knee}")

    def frames_of(*parts):
        return sorted({k["f"] for p in parts for k in T.get(p, [])})

    def key_meta(part, f, fallback="Torso"):
        for p in (part, fallback):
            for k in T.get(p, []):
                if abs(k["f"] - f) < 1e-6:
                    return k.get("e", "CubicV2"), k.get("d", "InOut")
        return "CubicV2", "InOut"

    torso_frames = frames_of("Torso") or [0]
    lower, upper = [], []
    for f in torso_frames:  # LowerTorso*UpperTorso == Torso exactly (both are eased half-slerps of the same keys)
        rot, off = eval_track(spec, T.get("Torso", []), f)
        lr = R.slerp_mat(R.IDENTITY, rot, waist_split)
        e, d = key_meta("Torso", f)
        lower.append(mkkey(f, lr, off, e, d))
        upper.append(mkkey(f, R.mat_mul(R.mat_t(lr), rot), [0, 0, 0], e, d))
    out["tracks"]["LowerTorso"], out["tracks"]["UpperTorso"] = lower, upper

    def waist_at(f):
        rot, _ = eval_track(spec, T.get("Torso", []), f)
        lr = R.slerp_mat(R.IDENTITY, rot, waist_split)
        return R.mat_mul(R.mat_t(lr), rot)

    for src, dst in (("Head", "Head"), ("Right Arm", "RightUpperArm"), ("Left Arm", "LeftUpperArm")):
        if src in T:  # parent frame (UpperTorso) == R6 Torso frame in world -> copy straight
            out["tracks"][dst] = [dict(k) for k in T[src]]
    for src, dst in (("Right Leg", "RightUpperLeg"), ("Left Leg", "LeftUpperLeg")):
        if src not in T:
            continue
        keys = []
        base = frames_of(src, "Torso")
        extra = set()
        if densify:
            extra = {float(f) for f in range(0, int(length(spec)) + 1, densify)} - set(base)
        for f in sorted(set(base) | extra):
            rot, off = eval_track(spec, T[src], f)
            w = waist_at(f)  # leg parent becomes LowerTorso: re-express through the waist
            e, d = key_meta(src, f)
            if densify:
                e, d = "Linear", "InOut"
            keys.append(mkkey(f, R.mat_mul(w, rot), R.mat_vec(w, off), e, d))
        out["tracks"][dst] = keys
    f0, fl = 0, length(spec)
    for part, ang in (("RightLowerArm", elbow), ("LeftLowerArm", elbow), ("RightLowerLeg", -knee), ("LeftLowerLeg", -knee),
                      ("RightHand", wrist), ("LeftHand", wrist)):
        if ang:
            out["tracks"][part] = [{"f": f0, "r": [ang, 0, 0], "e": "CubicV2", "d": "InOut"},
                                   {"f": fl, "r": [ang, 0, 0], "e": "CubicV2", "d": "InOut"}]
    for p, keys in T.items():  # weapons / extra joints follow their mapped parent
        if p not in R.R6["parts"]:
            out["tracks"][p] = [dict(k) for k in keys]
    for j in (out.get("extra_joints") or {}).values():
        j["parent"] = {"Right Arm": "RightHand", "Left Arm": "LeftHand", "Torso": "UpperTorso",
                       "Right Leg": "RightFoot", "Left Leg": "LeftFoot"}.get(j["parent"], j["parent"])
    return out


# ------------------------------------------------------------------ polish passes (deterministic levers)

def p_overlap(spec, arg):
    """'Right Arm:1,Head:2' -> delay those tracks by N frames (successive breaking of joints).
    Loops: keys wrap around and the seam is re-closed with keys at 0 and L (value sampled through the wrap)."""
    L = length(spec)
    for item in filter(None, arg.split(",")):
        part, n = item.rsplit(":", 1)
        part, n = part.strip(), float(n)
        keys = spec["tracks"].get(part, [])
        if spec.get("loop") and L and keys:
            body = [dict(k) for k in keys if k["f"] < L]          # drop the closing duplicate
            for k in body:
                k["f"] = round((k["f"] + n) % L, 3)
            body.sort(key=lambda k: k["f"])
            # value at the seam = interpolation from the last body key, through L, to the first body key
            a, b = body[-1], body[0]
            span = (L - a["f"]) + b["f"]
            t = (L - a["f"]) / span if span else 0
            rot, off = _interp(a, b, t)
            # pass THROUGH the seam (Linear on both sides); an InOut seam key stalls every offset track at once
            a["e"], a["d"] = "Linear", "InOut"
            seam = mkkey(0, rot, off, "Linear", "InOut")
            body = [k for k in body if k["f"] > 0]
            spec["tracks"][part] = [seam] + body + [dict(seam, f=L)]
            continue
        for k in keys:
            if k["f"] > 0:  # keep the first key anchored so the clip still starts posed
                k["f"] = round(min(k["f"] + n, L), 3)
    spec.setdefault("history", []).append(f"overlap {arg}")


def p_overshoot(spec, arg):
    """'Right Arm@18:0.15:3' -> the key at f18 overshoots by 15% of the incoming motion, settles 3 frames later."""
    for item in filter(None, arg.split(",")):
        part, rest = item.split("@")
        f, amt, n = rest.split(":")
        f, amt, n = float(f), float(amt), float(n)
        keys = sorted(spec["tracks"][part.strip()], key=lambda k: k["f"])
        idx = next(i for i, k in enumerate(keys) if abs(k["f"] - f) < 1e-6)
        if idx == 0:
            continue
        prev, cur = keys[idx - 1], keys[idx]
        settle = dict(cur)
        settle["f"] = f + n
        if idx + 1 < len(keys) and keys[idx + 1]["f"] <= settle["f"]:
            print(f"  overshoot {part}@{f}: next key too close, skipped")
            continue
        over = R.slerp_mat(key_rot(prev), key_rot(cur), 1 + amt)
        cur["r"] = R.mat_to_euler(over)
        if "p" in cur or "p" in prev:
            cur["p"] = [round(c + (c - p) * amt, 4) for p, c in zip(key_off(prev), key_off(cur))]
        cur["e"], cur["d"] = "CubicV2", "InOut"
        keys.append(settle)
        spec["tracks"][part.strip()] = sorted(keys, key=lambda k: k["f"])
    spec.setdefault("history", []).append(f"overshoot {arg}")


def p_exaggerate(spec, arg):
    """'Right Arm:10-22:1.25' -> scale rotation away from rest (and offsets) by 1.25 for keys in f10..22. Part '*' = all."""
    for item in filter(None, arg.split(",")):
        part, rng, s = item.split(":")
        a, b = (float(x) for x in rng.split("-"))
        s = float(s)
        for p, keys in spec["tracks"].items():
            if part != "*" and p != part:
                continue
            for k in keys:
                if a <= k["f"] <= b:
                    k["r"] = R.mat_to_euler(R.slerp_mat(R.IDENTITY, key_rot(k), s))
                    if "p" in k:
                        k["p"] = [round(x * s, 4) for x in k["p"]]
    spec.setdefault("history", []).append(f"exaggerate {arg}")


def p_retime(spec, arg):
    """'0-12:0.75' -> compress frames 0..12 to 75% length; everything after shifts to stay contiguous."""
    rng, s = arg.split(":")
    a, b = (float(x) for x in rng.split("-"))
    s = float(s)
    delta = (b - a) * (s - 1)
    for keys in spec["tracks"].values():
        for k in keys:
            if a <= k["f"] <= b:
                k["f"] = round(a + (k["f"] - a) * s, 3)
            elif k["f"] > b:
                k["f"] = round(k["f"] + delta, 3)
    for m in spec.get("markers", []):
        if a <= m["f"] <= b:
            m["f"] = round(a + (m["f"] - a) * s, 3)
        elif m["f"] > b:
            m["f"] = round(m["f"] + delta, 3)
    if spec.get("length"):
        spec["length"] = round(spec["length"] + delta, 3)
    spec.setdefault("history", []).append(f"retime {arg}")


def p_ease(spec, arg):
    """'Right Arm@12:Linear:In' or '*@12:Constant:In' -> set the easing leaving that key."""
    for item in filter(None, arg.split(",")):
        part, rest = item.split("@")
        f, style, d = rest.split(":")
        assert style in STYLES and d in DIRS, f"bad easing {style}/{d}"
        for p, keys in spec["tracks"].items():
            if part in ("*", p):
                for k in keys:
                    if abs(k["f"] - float(f)) < 1e-6:
                        k["e"], k["d"] = style, d
    spec.setdefault("history", []).append(f"ease {arg}")


def p_mirror(spec):
    """Swap left/right and flip yaw/roll — makes a left-handed version."""
    new = {}
    for p, keys in spec["tracks"].items():
        q = MIRROR.get(p, p)
        new[q] = [dict(k, r=[k.get("r", [0, 0, 0])[0], -k.get("r", [0, 0, 0])[1], -k.get("r", [0, 0, 0])[2]],
                       **({"p": [-k["p"][0], k["p"][1], k["p"][2]]} if "p" in k else {})) for k in keys]
    spec["tracks"] = new
    spec.setdefault("history", []).append("mirror")


# ------------------------------------------------------------------ schema check (runs before lint heuristics and before any Luau is emitted)

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def schema_check(spec, rig_file=None):
    """Structural validation. Returns a list of error strings (empty = valid): unknown part names for the rig,
    unknown easing style/direction, keys outside [0, length], bad rotation/offset vectors, bad marker frames."""
    errs = []
    if not isinstance(spec, dict) or not isinstance(spec.get("tracks"), dict):
        return ["spec has no 'tracks' object"]
    rigname = str(spec.get("rig", "")).upper()
    if rigname not in R.RIGS:
        return [f"rig '{spec.get('rig')}' is not one of {sorted(R.RIGS)}"]
    fps = spec.get("fps", 60)
    if not _is_num(fps) or fps <= 0:
        errs.append(f"fps {fps!r} must be a positive number")
    if spec.get("priority", "Action") not in PRIORITY:
        errs.append(f"priority '{spec.get('priority')}' is not one of {sorted(PRIORITY)}")
    for part, j in (spec.get("extra_joints") or {}).items():
        if not isinstance(j, dict) or "parent" not in j:
            errs.append(f"extra_joints['{part}'] needs a 'parent'")
    if errs:
        return errs
    rig = rig_of(spec, rig_file)
    for part, j in (spec.get("extra_joints") or {}).items():
        if j["parent"] not in rig["parts"] and j["parent"] != rig["root"]:
            errs.append(f"extra_joints['{part}'] parent '{j['parent']}' is not a part of rig {rigname}")
    L = spec.get("length")
    for part, keys in spec["tracks"].items():
        if part not in rig["parts"]:
            errs.append(f"track '{part}' is not a part of rig {rigname} (add it to extra_joints?)")
        if not isinstance(keys, list):
            errs.append(f"track '{part}' must be a list of keys")
            continue
        for i, k in enumerate(keys):
            tag = f"{part}[{i}]"
            if not isinstance(k, dict) or not _is_num(k.get("f")):
                errs.append(f"{tag}: key needs a numeric frame 'f'")
                continue
            if k["f"] < 0 or (_is_num(L) and L > 0 and k["f"] > L + 1e-6):
                errs.append(f"{tag}: key frame {k['f']:g} is outside 0..{L if _is_num(L) else '?'}")
            if k.get("e", "CubicV2") not in STYLES:
                errs.append(f"{tag} f{k['f']:g}: unknown easing style '{k.get('e')}' (use {', '.join(STYLES)})")
            if k.get("d", "InOut") not in DIRS:
                errs.append(f"{tag} f{k['f']:g}: unknown easing direction '{k.get('d')}' (use {', '.join(DIRS)})")
            for fld in ("r", "p"):
                v = k.get(fld)
                if v is not None and not (isinstance(v, (list, tuple)) and len(v) == 3 and all(_is_num(x) for x in v)):
                    errs.append(f"{tag} f{k['f']:g}: '{fld}' must be three numbers, got {v!r}")
    for i, m in enumerate(spec.get("markers", []) or []):
        if not isinstance(m, dict) or not m.get("name"):
            errs.append(f"marker[{i}] needs a name")
            continue
        mf = m.get("f")
        if not _is_num(mf) or mf < 0 or (_is_num(L) and L > 0 and mf > L + 1e-6):
            errs.append(f"marker '{m['name']}': frame {mf!r} is not a number within 0..{L if _is_num(L) else '?'}")
    return errs


# ------------------------------------------------------------------ lint (automated critique)

def lint(spec):
    """Heuristic critique. Returns list of (level, message). Thresholds are in 60fps-equivalent frames."""
    schema = schema_check(spec)
    if schema:  # nothing below is safe to run on malformed data
        return [("error", "schema: " + e) for e in schema]
    out = []
    fps = spec.get("fps", 60)
    k60 = 60.0 / fps
    T = spec["tracks"]
    keys = [k for ks in T.values() for k in ks]
    if not keys:
        return [("error", "no keys")]
    styles = [k.get("e", "CubicV2") for k in keys if not k.get("fl")]  # "fl" = easing chosen from the motion (life pass)
    lin = styles.count("Linear") / len(styles) if styles else 0
    if lin > 0.7:
        out.append(("warn", f"{lin:.0%} of keys are Linear -> mechanical. Ease into extremes (CubicV2 Out), keep Linear/Constant only into contacts."))
    if styles.count("Cubic"):
        out.append(("warn", "legacy 'Cubic' easing used — deprecated (direction bug); use CubicV2."))
    L = length(spec)
    # overlap / offset
    tf = {k["f"] for p in TORSO for k in T.get(p, [])}
    ext = [k["f"] for p in EXTREMITIES for k in T.get(p, [])]
    flowed = all(k.get("fl") for k in keys)  # life-keyed: key frames no longer show overlap; lint the pre-life spec for it
    if tf and ext and not flowed:
        same = sum(1 for f in ext if f in tf) / len(ext)
        if same > 0.8:
            out.append(("warn", f"{same:.0%} of extremity keys share frames with the torso -> no overlap. Delay arms/head 1-2f@30 (2-4f@60): polish --overlap."))
    # twinning
    for a, b in (("Right Arm", "Left Arm"), ("RightUpperArm", "LeftUpperArm"), ("Right Leg", "Left Leg"), ("RightUpperLeg", "LeftUpperLeg")):
        if a in T and b in T:
            fa = {k["f"] for k in T[a]}
            fb = {k["f"] for k in T[b]}
            if fa == fb and len(fa) > 2:
                mirrored = 0
                posed = 0
                for f in fa:
                    ra = eval_track(spec, T[a], f)[0]
                    rb = eval_track(spec, T[b], f)[0]
                    if R.angle_between(R.IDENTITY, ra) < 5 and R.angle_between(R.IDENTITY, rb) < 5:
                        continue  # both at rest: not evidence of twinning
                    posed += 1
                    if R.angle_between(ra, rb) < 6:
                        mirrored += 1
                if posed >= 2 and mirrored / posed > 0.6:
                    out.append(("warn", f"{a}/{b} keyed on identical frames with near-identical poses -> twinning/symmetry looks stiff. Offset timing or vary poses."))
    # holds, pops, energy
    step = max(1, int(round(fps / 60))) if fps > 60 else 1
    frames = [f for f in range(0, int(L) + 1, step)]
    prev = None
    still = 0
    worst_still = (0, 0)
    pops = []
    maxdev = {}
    for f in frames:
        cur = {p: eval_track(spec, ks, f) for p, ks in T.items()}
        for p, (rot, off) in cur.items():
            maxdev[p] = max(maxdev.get(p, 0), R.angle_between(R.IDENTITY, rot))
        if prev:
            speed = max(R.angle_between(prev[p][0], cur[p][0]) for p in cur)
            if speed * k60 < 0.15:
                still += 1
                if still > worst_still[0]:
                    worst_still = (still, f)
            else:
                still = 0
            for p in cur:
                s = R.angle_between(prev[p][0], cur[p][0]) * k60
                if s > 45:
                    pops.append((f, p, round(s)))
        prev = cur
    if worst_still[0] * k60 >= 12 and not spec.get("stepped"):
        out.append(("warn", f"dead hold: whole body frozen {worst_still[0]} frames ending f{worst_still[1]}. Use a moving hold (2-5% drift) or settle key."))
    if pops:
        f, p, s = pops[0]
        out.append(("info", f"{len(pops)} very fast frames (e.g. f{f} {p} {s}°/frame@60). Fine for smears/contacts; a pop if unintended."))
    for p, ks in T.items():
        if L and len(ks) > 0.5 * (L + 1) and len(ks) > 12:
            out.append(("warn", f"{p}: keys on >50% of frames -> baked/jittery. Reduce to key poses + breakdowns."))
    if spec.get("category") in ("combat", "weapon", "ability"):
        big = [p for p in maxdev if maxdev[p] >= 25]
        if not big:
            out.append(("warn", "no part rotates >=25° from rest in a combat clip -> poses too timid; push extremes 10-30% (polish --exaggerate)."))
        m = {x["name"]: x["f"] for x in spec.get("markers", [])}
        if "HitStart" not in m:
            out.append(("warn", "combat clip without a HitStart marker -> gameplay can't sync hitbox/VFX (see the combat frame-data notes)."))
        else:
            ant = m["HitStart"] * k60
            rec = (L - m.get("HitEnd", m["HitStart"])) * k60
            out.append(("info", f"startup {ant:.0f}f@60 (light 5-9, heavy 12-20), recovery {rec:.0f}f@60; follow-through usually >= startup."))
    for p in TORSO | {"HumanoidRootPart"}:
        for k in T.get(p, []):
            if "p" in k and math.dist(k["p"], [0, 0, 0]) > 2.0:
                out.append(("warn", f"{p} offset {k['p']} at f{k['f']}: large root displacement snaps back in game — move the HumanoidRootPart by script on a marker instead."))
                break
    # every part keeps moving (user rule 2026-11-11): no part slower than 1.5 deg/s for >= 100 ms
    if spec.get("rig", "").upper() == "R15" and not spec.get("stepped"):
        import anim_life  # noqa: E402  (lazy: anim_life imports this module)
        mr = anim_life.motion_report(spec)
        bad = sorted(((ms, p) for p, (ms, _) in mr.items() if ms >= 100), reverse=True)
        if bad:
            out.append(("warn", f"{len(bad)} parts stand still >= 100 ms (worst: " + ", ".join(f"{p} {ms}ms" for ms, p in bad[:4])
                        + "). Every part should keep moving: polish --life."))
    if spec.get("loop"):
        for p, ks in T.items():
            a = eval_track(spec, ks, 0)[0]
            b = eval_track(spec, ks, L)[0]
            if R.angle_between(a, b) > 2:
                out.append(("warn", f"loop seam: {p} differs {R.angle_between(a, b):.1f}° between f0 and f{L} — Roblox does not interpolate last->first; end on a copy of the first pose."))
    if not out:
        out.append(("ok", "no heuristic problems found — now judge it visually against the reference."))
    return [("info", f"schema: ok ({len(T)} tracks, {len(keys)} keys, rig {spec['rig'].upper()})")] + out


# ------------------------------------------------------------------ build (Luau / rbxmx)

def joint_cf(rig, part, rot, off):
    jr, jp = R.rel_to_joint(rig, part, rot, off)
    return [round(v, 5) for v in jp + jr[0] + jr[1] + jr[2]]


def keyframe_table(spec, rig, bake=0):
    """[(time_s, [(part, cf12, weight, style, dir)], [markers])]"""
    fps = spec.get("fps", 60)
    T = spec["tracks"]
    if bake:
        frames = list(range(0, int(length(spec)) + 1, bake))
        if frames[-1] != length(spec):
            frames.append(length(spec))
        rows = []
        for f in frames:
            poses = []
            for p, ks in T.items():
                rot, off = eval_track(spec, ks, f)
                poses.append((p, joint_cf(rig, p, rot, off), 1.0, "Linear", "In"))
            rows.append([f / fps, poses, []])
    else:
        rows = []
        for f in all_frames(spec):
            poses = []
            for p, ks in T.items():
                for k in ks:
                    if abs(k["f"] - f) < 1e-6:
                        poses.append((p, joint_cf(rig, p, key_rot(k), key_off(k)), 1.0, k.get("e", "CubicV2"), k.get("d", "InOut")))
            rows.append([f / fps, poses, []])
    for m in spec.get("markers", []):
        t = m["f"] / fps
        row = min(rows, key=lambda r: abs(r[0] - t)) if rows else None
        if row is None or abs(row[0] - t) > 1e-6:
            row = [t, [], []]
            rows.append(row)
        row[2].append((m["name"], m.get("value", "")))
    rows.sort(key=lambda r: r[0])
    return rows


def _lua_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


LUAU_RUNTIME = r'''
local ServerStorage = game:GetService("ServerStorage")
local KSP = game:GetService("KeyframeSequenceProvider")
local Players = game:GetService("Players")

local function build(): KeyframeSequence
	local kfs = Instance.new("KeyframeSequence")
	kfs.Name = DATA.name
	kfs.Loop = DATA.loop
	kfs.Priority = Enum.AnimationPriority[DATA.priority]
	for _, row in DATA.keyframes do
		local kf = Instance.new("Keyframe")
		kf.Time = row.t
		local posesByPath: {[string]: Pose} = {}
		local function getPose(path: {string}, upto: number): Pose
			local key = table.concat(path, "/", 1, upto)
			local existing = posesByPath[key]
			if existing then return existing end
			local pose = Instance.new("Pose")
			pose.Name = path[upto]
			pose.Weight = 0 -- container only (no key) unless set below
			pose.CFrame = CFrame.identity
			pose.Parent = if upto == 1 then kf else getPose(path, upto - 1)
			posesByPath[key] = pose
			return pose
		end
		for _, p in row.poses do
			local path = DATA.paths[p[1]]
			local pose = getPose(path, #path)
			local c = p[2]
			pose.CFrame = CFrame.new(c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10], c[11], c[12])
			pose.Weight = p[3]
			pose.EasingStyle = Enum.PoseEasingStyle[p[4]]
			pose.EasingDirection = Enum.PoseEasingDirection[p[5]]
		end
		for _, m in row.markers do
			local marker = Instance.new("KeyframeMarker")
			marker.Name = m[1]
			marker.Value = m[2]
			marker.Parent = kf
		end
		kf.Parent = kfs
	end
	return kfs
end

local function folder(parent: Instance, name: string): Instance
	local f = parent:FindFirstChild(name)
	if not f then
		f = Instance.new("Folder")
		f.Name = name
		f.Parent = parent
	end
	return f
end

-- 1) build + store (pipeline copy, and an Animation Editor-loadable copy)
local kfs = build()
local store = folder(folder(ServerStorage, "AnimPipeline"), DATA.assetId)
local old = store:FindFirstChild(DATA.name)
if old then old:Destroy() end
kfs.Parent = store
local saves = folder(folder(ServerStorage, "RBX_ANIMSAVES"), PREVIEW_NAME)
local oldSave = saves:FindFirstChild(DATA.name)
if oldSave then oldSave:Destroy() end
kfs:Clone().Parent = saves

-- 2) temporary id (Studio session only — publish via the Animation Editor for real use)
local tempId = KSP:RegisterKeyframeSequence(kfs)

-- 3) preview rig on a neutral stage, far from the map
local stage = workspace:FindFirstChild("AnimPipelineStage")
if not stage then
	stage = Instance.new("Model")
	stage.Name = "AnimPipelineStage"
	local floor = Instance.new("Part")
	floor.Name = "Floor"; floor.Anchored = true; floor.Size = Vector3.new(60, 1, 60)
	floor.CFrame = CFrame.new(STAGE_POS - Vector3.new(0, 3.5, 0)); floor.Color = Color3.fromRGB(235, 235, 235)
	floor.Parent = stage
	local wall = Instance.new("Part")
	wall.Name = "Backdrop"; wall.Anchored = true; wall.Size = Vector3.new(60, 40, 1)
	wall.CFrame = CFrame.new(STAGE_POS + Vector3.new(0, 16, 20)); wall.Color = Color3.fromRGB(235, 235, 235)
	wall.Parent = stage
	stage.Parent = workspace
end
local rig = stage:FindFirstChild(PREVIEW_NAME) :: Model?
if not rig then
	local ok, made = pcall(function()
		-- The non-Async constructor is deprecated; prefer the Async one when this Studio build has it.
		local desc, rigType = Instance.new("HumanoidDescription"), Enum.HumanoidRigType[DATA.rig]
		local okAsync, model = pcall(function() return (Players :: any):CreateHumanoidModelFromDescriptionAsync(desc, rigType) end)
		if okAsync and model then return model end
		return Players:CreateHumanoidModelFromDescription(desc, rigType)
	end)
	if not ok or not made then
		return "NO_RIG: insert a " .. DATA.rig .. " dummy (Avatar tab > Rig Builder), name it " .. PREVIEW_NAME .. ", put it in workspace.AnimPipelineStage, rerun. (" .. tostring(made) .. ")"
	end
	rig = made
	rig.Name = PREVIEW_NAME
	rig.Parent = stage
end
assert(rig)
local hrp = rig:FindFirstChild("HumanoidRootPart") :: BasePart
hrp.Anchored = true
rig:PivotTo(CFrame.new(STAGE_POS))
EXTRA_JOINTS(rig)
local humanoid = rig:FindFirstChildOfClass("Humanoid") :: Humanoid
local animator = humanoid:FindFirstChildOfClass("Animator") or Instance.new("Animator", humanoid)
local anim = Instance.new("Animation")
anim.AnimationId = tempId
anim.Name = "PipelinePreview"
local prev = rig:FindFirstChild("PipelinePreview")
if prev then prev:Destroy() end
anim.Parent = rig
rig:SetAttribute("PipelineAnimId", tempId)
rig:SetAttribute("PipelineLength", DATA.length)

local cam = STAGE_POS + CAMERA_OFFSET
return string.format('{"ok":true,"tempId":"%s","length":%.4f,"rig":"%s","camera_position":[%.2f,%.2f,%.2f],"look_at_position":[%.2f,%.2f,%.2f]}',
	tempId, DATA.length, rig:GetFullName(), cam.X, cam.Y, cam.Z, STAGE_POS.X, STAGE_POS.Y + 0.5, STAGE_POS.Z)
'''


def camera_offset(spec):
    c = spec.get("camera", {})
    yaw, pitch, dist = math.radians(c.get("yaw", 30)), math.radians(c.get("pitch", 8)), c.get("distance", 12)
    # yaw 0 = camera in FRONT of the character (character faces -Z, so camera on -Z side)
    return [round(-math.sin(yaw) * math.cos(pitch) * dist, 3), round(math.sin(pitch) * dist + 0.5, 3),
            round(-math.cos(yaw) * math.cos(pitch) * dist, 3)]


JOINT_FINDER_LUA = """-- A rig joint is a Motor6D, or an AnimationConstraint on rigs with the Avatar Joint Upgrade. Both are found by Part1.
-- Only Transform is ever written to a joint (never C0/C1, which are read-only on an AnimationConstraint).
local function findJoint(rig: Model, partName: string): Instance?
	for _, d in rig:GetDescendants() do
		if (d:IsA("Motor6D") or d:IsA("AnimationConstraint")) and d.Part1 and d.Part1.Name == partName then
			return d
		end
	end
	return nil
end"""


def extra_joints_lua(spec):
    lines = [JOINT_FINDER_LUA, "local function EXTRA_JOINTS(rig: Model)"]
    for part, j in (spec.get("extra_joints") or {}).items():
        lines.append(f'\t-- {part}: expects a Motor6D (or AnimationConstraint) with Part1 named {_lua_str(part)}, attached under {_lua_str(j["parent"])}')
        lines.append(f'\tif not findJoint(rig, {_lua_str(part)}) then warn("missing extra joint for {part} - attach your weapon or prop with a Motor6D (see the rigging notes)") end')
    lines.append("end")
    return "\n".join(lines)


def emit_luau(spec, rows, rig):
    paths = {p: R.chain_to_root(rig, p) for p in spec["tracks"]}
    fps = spec.get("fps", 60)
    name = f'{spec.get("id", "ANIM")}_v{int(spec.get("version", 1)):03d}'
    L = []
    L.append(f"-- GENERATED by anim_spec.py from {spec.get('id')} v{spec.get('version', 1)} — do not hand-edit; edit the spec and rebuild.")
    L.append("--!nonstrict")
    L.append("local DATA = {")
    L.append(f'\tname = {_lua_str(name)}, assetId = {_lua_str(spec.get("id", "ANIM"))}, rig = {_lua_str(spec["rig"].upper())},')
    L.append(f'\tloop = {"true" if spec.get("loop") else "false"}, priority = {_lua_str(spec.get("priority", "Action"))}, length = {length(spec) / fps:.4f},')
    L.append("\tpaths = {")
    for p, path in paths.items():
        L.append(f"\t\t[{_lua_str(p)}] = {{{', '.join(_lua_str(x) for x in path)}}},")
    L.append("\t},")
    L.append("\tkeyframes = {")
    for t, poses, markers in rows:
        ps = ", ".join("{%s, {%s}, %g, %s, %s}" % (_lua_str(p), ", ".join(f"{v:g}" for v in cf), w, _lua_str(e), _lua_str(d))
                       for p, cf, w, e, d in poses)
        ms = ", ".join("{%s, %s}" % (_lua_str(n), _lua_str(v)) for n, v in markers)
        L.append(f"\t\t{{t = {t:.4f}, poses = {{{ps}}}, markers = {{{ms}}}}},")
    L.append("\t},")
    L.append("}")
    sp = spec.get("stage_position", [0, 500, 0])
    L.append(f"local STAGE_POS = Vector3.new({sp[0]}, {sp[1]}, {sp[2]})")
    co = camera_offset(spec)
    L.append(f"local CAMERA_OFFSET = Vector3.new({co[0]}, {co[1]}, {co[2]})")
    L.append(f'local PREVIEW_NAME = "AnimPreview_{spec["rig"].upper()}"')
    L.append(extra_joints_lua(spec))
    L.append(LUAU_RUNTIME)
    return "\n".join(L)


def emit_pose_luau(spec, rig, frame):
    lines = [f"-- GENERATED: static pose of {spec.get('id')} v{spec.get('version', 1)} at frame {frame} (sets joint Transform on the preview rig: Motor6D or AnimationConstraint)",
             f'local rig = workspace:FindFirstChild("AnimPipelineStage") and workspace.AnimPipelineStage:FindFirstChild("AnimPreview_{spec["rig"].upper()}")',
             'if not rig then return "NO_RIG: run the build script first" end',
             "local motors = {}",
             "-- Motor6D, or AnimationConstraint on R15 rigs with the Avatar Joint Upgrade (Transform works the same; C0/C1/Part0/Part1 are read-only there)",
             "for _, m in rig:GetDescendants() do if (m:IsA(\"Motor6D\") or m:IsA(\"AnimationConstraint\")) and m.Part1 then motors[m.Part1.Name] = m end end",
             "local missing = {}"]
    for p, ks in spec["tracks"].items():
        rot, off = eval_track(spec, ks, frame)
        cf = joint_cf(rig, p, rot, off)
        lines.append(f'if motors[{_lua_str(p)}] then motors[{_lua_str(p)}].Transform = CFrame.new({", ".join(f"{v:g}" for v in cf)}) else table.insert(missing, {_lua_str(p)}) end')
    lines.append(f'return "posed frame {frame}" .. (if #missing > 0 then " missing: " .. table.concat(missing, ",") else "")')
    return "\n".join(lines)


def emit_rbxmx(spec, rows, rig):
    """KeyframeSequence as rbxmx (right-click ServerStorage > Insert from File). Prefer the Luau route."""
    ref = [0]

    def nid():
        ref[0] += 1
        return f"RBX{ref[0]:08X}"

    def cf_xml(c):
        names = ["X", "Y", "Z", "R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22"]
        return "".join(f"<{n}>{v:g}</{n}>" for n, v in zip(names, c))

    fps = spec.get("fps", 60)
    out = ['<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" version="4">',
           f'<Item class="KeyframeSequence" referent="{nid()}"><Properties>'
           f'<string name="Name">{spec.get("id", "ANIM")}_v{int(spec.get("version", 1)):03d}</string>'
           f'<bool name="Loop">{"true" if spec.get("loop") else "false"}</bool>'
           f'<token name="Priority">{PRIORITY[spec.get("priority", "Action")]}</token></Properties>']
    paths = {p: R.chain_to_root(rig, p) for p in spec["tracks"]}
    for t, poses, markers in rows:
        out.append(f'<Item class="Keyframe" referent="{nid()}"><Properties><string name="Name">Keyframe</string><float name="Time">{t:.4f}</float></Properties>')
        tree = {}
        for p, cf, w, e, d in poses:
            node = tree
            for name in paths[p][:-1]:
                node = node.setdefault(name, {"_": None, "c": {}})["c"]
            node.setdefault(paths[p][-1], {"_": None, "c": {}})["_"] = (cf, w, e, d)

        def write(node):
            for name, v in node.items():
                cf, w, e, d = v["_"] or ([0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1], 0, "Linear", "In")
                out.append(f'<Item class="Pose" referent="{nid()}"><Properties><string name="Name">{name}</string>'
                           f'<CoordinateFrame name="CFrame">{cf_xml(cf)}</CoordinateFrame>'
                           f'<token name="EasingStyle">{STYLES.index(e)}</token><token name="EasingDirection">{DIRS.index(d)}</token>'
                           f'<float name="Weight">{w:g}</float></Properties>')
                write(v["c"])
                out.append("</Item>")
        write(tree)
        for n, v in markers:
            out.append(f'<Item class="KeyframeMarker" referent="{nid()}"><Properties><string name="Name">{n}</string><string name="Value">{v}</string></Properties></Item>')
        out.append("</Item>")
    out.append("</Item></roblox>")
    return "\n".join(out)


# ------------------------------------------------------------------ chart

def chart(spec, png=None, md=False):
    fps = spec.get("fps", 60)
    L = int(length(spec))
    T = spec["tracks"]
    speeds = {p: [] for p in T}
    prev = {p: eval_track(spec, ks, 0)[0] for p, ks in T.items()}
    for f in range(1, L + 1):
        for p, ks in T.items():
            cur = eval_track(spec, ks, f)[0]
            speeds[p].append(R.angle_between(prev[p], cur))
            prev[p] = cur
    if md:
        print(f"| Part | keys (frames @{fps}) | easing | peak °/f |")
        print("|---|---|---|---|")
        for p, ks in T.items():
            frames_txt = ", ".join("%g" % k["f"] for k in ks)
            eases_txt = ", ".join(sorted({k.get("e", "CubicV2") + "/" + k.get("d", "InOut") for k in ks}))
            print(f"| {p} | {frames_txt} | {eases_txt} | {max(speeds[p] or [0]):.1f} |")
        if spec.get("markers"):
            print("\nMarkers: " + ", ".join(f"{m['name']}@{m['f']}" for m in spec["markers"]))
    if png:
        from PIL import Image, ImageDraw
        W, H, pad = 1100, 520, 50
        img = Image.new("RGB", (W, H), "white")
        dr = ImageDraw.Draw(img)
        peak = max((max(v) for v in speeds.values() if v), default=1) or 1
        colors = [(220, 50, 50), (40, 120, 220), (40, 170, 80), (230, 140, 20), (140, 60, 200), (20, 170, 170),
                  (200, 80, 160), (100, 100, 100), (160, 120, 40), (0, 0, 0), (90, 160, 230), (230, 90, 90),
                  (60, 200, 140), (180, 180, 40), (120, 40, 40), (40, 40, 140)]
        dr.rectangle([pad, pad, W - pad, H - pad], outline=(180, 180, 180))
        for f in range(0, L + 1, max(1, L // 20)):
            x = pad + (W - 2 * pad) * f / max(L, 1)
            dr.line([x, H - pad, x, H - pad + 5], fill=(0, 0, 0))
            dr.text((x - 6, H - pad + 8), str(f), fill=(0, 0, 0))
        for m in spec.get("markers", []):
            x = pad + (W - 2 * pad) * m["f"] / max(L, 1)
            dr.line([x, pad, x, H - pad], fill=(255, 0, 255))
            dr.text((x + 3, pad + 3), m["name"], fill=(255, 0, 255))
        for i, (p, v) in enumerate(speeds.items()):
            c = colors[i % len(colors)]
            pts = [(pad + (W - 2 * pad) * (f + 1) / max(L, 1), H - pad - (H - 2 * pad) * s / peak) for f, s in enumerate(v)]
            if len(pts) > 1:
                dr.line(pts, fill=c, width=2)
            for k in T[p]:
                x = pad + (W - 2 * pad) * k["f"] / max(L, 1)
                dr.ellipse([x - 3, H - pad - 3 - 8 * i % 40, x + 3, H - pad + 3 - 8 * i % 40], outline=c)
            dr.text((W - pad - 150, pad + 5 + 14 * i), f"{p}", fill=c)
        dr.text((pad, 15), f"{spec.get('id')} v{spec.get('version', 1)} — angular speed per part (°/frame @{fps}); peaks = fast spacing, valleys = eases/holds; magenta = markers",
                fill=(0, 0, 0))
        img.save(png)
        print(f"wrote {png}")


# ------------------------------------------------------------------ import from Studio dump

def import_dump(dump, spec_id, fps=60):
    """dump = JSON produced by the 'dump KeyframeSequence' snippet in the animsmith pipeline docs."""
    rig_name = dump.get("rig") or ("R15" if any(p["name"] == "UpperTorso" for kf in dump["keyframes"] for p in kf["poses"]) else "R6")
    rig = R.load_rig(rig_name)
    spec = {"id": spec_id, "version": 1, "name": dump.get("name", spec_id), "rig": rig_name, "space": "rel", "fps": fps,
            "loop": dump.get("loop", False), "priority": dump.get("priority", "Action"), "tracks": {}, "markers": [],
            "history": [f"imported from Studio dump {dump.get('name')}"]}
    for kf in dump["keyframes"]:
        f = round(kf["t"] * fps, 3)
        for p in kf["poses"]:
            if p.get("w", 1) <= 0 or p["name"] == "HumanoidRootPart":
                continue
            if p["name"] not in rig["parts"]:
                rig = R.add_extra_joints(rig, {p["name"]: {"parent": p.get("parent", "HumanoidRootPart")}})
                spec.setdefault("extra_joints", {})[p["name"]] = {"parent": p.get("parent", "HumanoidRootPart")}
            c = p["cf"]
            rot = [c[3:6], c[6:9], c[9:12]]
            rel, off = R.joint_to_rel(rig, p["name"], rot, c[0:3])
            spec["tracks"].setdefault(p["name"], []).append(mkkey(f, rel, off, p.get("es", "CubicV2"), p.get("ed", "InOut")))
        for m in kf.get("markers", []):
            spec["markers"].append({"name": m[0], "value": m[1] if len(m) > 1 else "", "f": f})
    spec["length"] = round(dump.get("length", 0) * fps, 3) or None
    if not spec["length"]:
        spec.pop("length")
    return spec


# ------------------------------------------------------------------ CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["new", "lint", "retarget", "polish", "build", "pose", "chart", "import"])
    ap.add_argument("spec")
    ap.add_argument("-o", "--out")
    ap.add_argument("--id")
    ap.add_argument("--rig", default="R15")
    ap.add_argument("--rig-file")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--length", type=float, default=60)
    ap.add_argument("--to", default="R15")
    ap.add_argument("--waist-split", type=float, default=0.5)
    ap.add_argument("--elbow", type=float, default=8.0)
    ap.add_argument("--knee", type=float, default=0.0)
    ap.add_argument("--densify", type=int, default=0)
    ap.add_argument("--overlap")
    ap.add_argument("--overshoot")
    ap.add_argument("--exaggerate")
    ap.add_argument("--retime")
    ap.add_argument("--ease")
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--life", help="sway amp[:drag gain], e.g. 1.0 or 1.0:1.2 — no part ever stationary (anim_life)")
    ap.add_argument("--luau")
    ap.add_argument("--rbxmx")
    ap.add_argument("--bake", type=int, default=0)
    ap.add_argument("--frame", type=float, default=0)
    ap.add_argument("--png")
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()

    if a.cmd == "new":
        rig = R.load_rig(a.rig)
        spec = {"id": a.id or "ANIM-XXX-0000", "version": 1, "name": a.id or "untitled", "rig": a.rig.upper(), "space": "rel",
                "fps": a.fps, "length": a.length, "loop": False, "priority": "Action", "category": "combat",
                "camera": {"yaw": 30, "pitch": 8, "distance": 12}, "markers": [],
                "tracks": {p: [{"f": 0, "r": [0, 0, 0], "e": "CubicV2", "d": "InOut"}] for p in rig["parts"]},
                "history": ["new"]}
        save(spec, a.spec)
        return
    if a.cmd == "import":
        spec = import_dump(load(a.spec), a.id or "ANIM-IMPORT-0000", a.fps)
        save(spec, a.out)
        return
    spec = load(a.spec)
    if a.cmd in ("build", "pose"):
        bad = schema_check(spec, a.rig_file)
        if bad:  # fail before any Luau/rbxmx is written
            for e in bad:
                print(f"[ERROR] schema: {e}")
            sys.exit(1)
    if a.cmd == "lint":
        res = lint(spec)
        for lvl, msg in res:
            print(f"[{lvl.upper():5}] {msg}")
        if any(lvl == "error" for lvl, _ in res):
            sys.exit(1)
    elif a.cmd == "retarget":
        save(retarget(spec, a.to, a.waist_split, a.elbow, a.knee, densify=a.densify), a.out)
    elif a.cmd == "polish":
        if a.retime:
            p_retime(spec, a.retime)
        if a.overlap:
            p_overlap(spec, a.overlap)
        if a.exaggerate:
            p_exaggerate(spec, a.exaggerate)
        if a.overshoot:
            p_overshoot(spec, a.overshoot)
        if a.ease:
            p_ease(spec, a.ease)
        if a.mirror:
            p_mirror(spec)
        if a.life:
            import anim_life  # noqa: E402
            amp, _, drag = a.life.partition(":")
            anim_life.apply(spec, float(amp or 1), float(drag or 1))
        if a.out and os.path.abspath(a.out) != os.path.abspath(a.spec):
            spec["version"] = int(spec.get("version", 1)) + 1  # new file = new version
        save(spec, a.out or a.spec)
    elif a.cmd == "build":
        rig = rig_of(spec, a.rig_file)
        rows = keyframe_table(spec, rig, a.bake)
        if a.luau:
            open(a.luau, "w", encoding="utf-8").write(emit_luau(spec, rows, rig))
            print(f"wrote {a.luau}  ({len(rows)} keyframes)")
        if a.rbxmx:
            open(a.rbxmx, "w", encoding="utf-8").write(emit_rbxmx(spec, rows, rig))
            print(f"wrote {a.rbxmx}")
    elif a.cmd == "pose":
        rig = rig_of(spec, a.rig_file)
        text = emit_pose_luau(spec, rig, a.frame)
        if a.luau:
            open(a.luau, "w", encoding="utf-8").write(text)
            print(f"wrote {a.luau}")
        else:
            print(text)
    elif a.cmd == "chart":
        chart(spec, a.png, a.md)


if __name__ == "__main__":
    main()
