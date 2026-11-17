"""Bake AnimSpecs into a browser preview (preview before Studio).

For every spec it evaluates each part with the pipeline's own evaluator (anim_spec.eval_track: same easing + slerp
as the Studio build), runs forward kinematics on an approximate block rig (R6 or R15), and writes world transforms
per frame at --hz. It also measures ground contact: lowest foot point per frame (penetration / float), which is the
automated "feet planted?" check the Luau build can't give you before Studio.

  python kit/scripts/anim_preview.py --out <dir> --clip "ID|label|spec1.json,spec2.json|ref.gif" ...
Writes <dir>/data.json (+ <dir>/ref_<ID>.jpg sprite sheets of the reference frames).

Rig geometry is approximate (blocky R15 joint heights from the standard rig, thigh 0.9 / shin 0.8); dump the real rig
(the animsmith "dump rig" snippet) and compare before trusting sub-0.05-stud contact numbers.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_rig as R  # noqa: E402
import anim_spec as A  # noqa: E402

# part -> (parent, joint position in parent's local frame, child centre relative to joint, size, shape)
GEO = {
    "R6": {
        "hrp_y": 3.0,
        "parts": {
            "Torso": ("HumanoidRootPart", (0, 0, 0), (0, 0, 0), (2, 2, 1), "torso"),
            "Head": ("Torso", (0, 1, 0), (0, 0.6, 0), (1.2, 1.2, 1.2), "head"),
            "Right Arm": ("Torso", (1, 0.5, 0), (0.5, -0.5, 0), (1, 2, 1), "limb"),
            "Left Arm": ("Torso", (-1, 0.5, 0), (-0.5, -0.5, 0), (1, 2, 1), "limb"),
            "Right Leg": ("Torso", (1, -1, 0), (-0.5, -1, 0), (1, 2, 1), "limb"),
            "Left Leg": ("Torso", (-1, -1, 0), (0.5, -1, 0), (1, 2, 1), "limb"),
        },
        "feet": {"Right Leg": -1.0, "Left Leg": -1.0},  # local y of the sole
    },
    "R15": {
        "hrp_y": 3.0,
        "parts": {
            "LowerTorso": ("HumanoidRootPart", (0, -1, 0), (0, 0.2, 0), (2, 0.4, 1), "torso"),
            "UpperTorso": ("LowerTorso", (0, 0.2, 0), (0, 0.8, 0), (2, 1.6, 1), "torso"),
            "Head": ("UpperTorso", (0, 0.8, 0), (0, 0.6, 0), (1.2, 1.2, 1.2), "head"),
            "RightUpperArm": ("UpperTorso", (1, 0.56, 0), (0.5, -0.31, 0), (1, 1.02, 1), "limb"),
            "RightLowerArm": ("RightUpperArm", (0, -0.45, 0), (0, -0.33, 0), (1, 0.76, 1), "limb"),
            "RightHand": ("RightLowerArm", (0, -0.37, 0), (0, -0.16, 0), (1, 0.34, 1), "limb"),
            "LeftUpperArm": ("UpperTorso", (-1, 0.56, 0), (-0.5, -0.31, 0), (1, 1.02, 1), "limb"),
            "LeftLowerArm": ("LeftUpperArm", (0, -0.45, 0), (0, -0.33, 0), (1, 0.76, 1), "limb"),
            "LeftHand": ("LeftLowerArm", (0, -0.37, 0), (0, -0.16, 0), (1, 0.34, 1), "limb"),
            "RightUpperLeg": ("LowerTorso", (0.5, -0.2, 0), (0, -0.45, 0), (1, 1.1, 1), "limb"),
            "RightLowerLeg": ("RightUpperLeg", (0, -0.45, 0), (0, -0.375, 0), (1, 0.85, 1), "limb"),
            "RightFoot": ("RightLowerLeg", (0, -0.425, 0), (0, -0.15, 0), (1, 0.3, 1), "limb"),
            "LeftUpperLeg": ("LowerTorso", (-0.5, -0.2, 0), (0, -0.45, 0), (1, 1.1, 1), "limb"),
            "LeftLowerLeg": ("LeftUpperLeg", (0, -0.45, 0), (0, -0.375, 0), (1, 0.85, 1), "limb"),
            "LeftFoot": ("LeftLowerLeg", (0, -0.425, 0), (0, -0.15, 0), (1, 0.3, 1), "limb"),
        },
        "feet": {"RightFoot": -0.15, "LeftFoot": -0.15},
    },
}


def _apply(rot, pos, v):
    return [pos[i] + sum(rot[i][k] * v[k] for k in range(3)) for i in range(3)]


def fk(spec, rig_name, f):
    """World (rot, centre) of every part at frame f, plus per-part joint frame."""
    geo = GEO[rig_name]
    T = spec["tracks"]
    joint = {"HumanoidRootPart": (R.IDENTITY, [0.0, geo["hrp_y"], 0.0])}  # rest-aligned frame of each part, at its centre
    out = {}
    for part, (parent, jp, cc, size, shape) in geo["parts"].items():
        prot, ppos = joint[parent]
        rel, off = A.eval_track(spec, T.get(part, []), f)
        jworld = _apply(prot, ppos, [jp[i] + off[i] for i in range(3)])
        wrot = R.mat_mul(prot, rel)
        centre = _apply(wrot, jworld, cc)
        joint[part] = (wrot, centre)
        out[part] = (wrot, centre)
    return out


def sole_y(rig_name, world):
    lows = {}
    for part, ly in GEO[rig_name]["feet"].items():
        rot, c = world[part]
        sx, _, sz = GEO[rig_name]["parts"][part][3]
        ys = [_apply(rot, c, [dx * sx / 2, ly, dz * sz / 2])[1] for dx in (-1, 1) for dz in (-1, 1)]
        lows[part] = min(ys)
    return lows


def bake(spec, hz):
    rig = spec["rig"].upper()
    fps = spec.get("fps", 60)
    L = A.length(spec)
    n = int(round(L / fps * hz)) + (0 if spec.get("loop") else 1)
    parts = list(GEO[rig]["parts"])
    # extra_joints parts (weapons, props, capes) have no block geometry here: they are skipped in FK and reported
    skipped = sorted(p for p in spec["tracks"] if p not in GEO[rig]["parts"])
    frames, contact = [], []
    for i in range(n):
        f = i * fps / hz
        w = fk(spec, rig, f)
        row = []
        for p in parts:
            rot, c = w[p]
            q = R.mat_to_quat(rot)  # w, x, y, z
            row += [round(c[0], 3), round(c[1], 3), round(c[2], 3), round(q[1], 4), round(q[2], 4), round(q[3], 4), round(q[0], 4)]
        frames.append(row)
        contact.append(round(min(sole_y(rig, w).values()), 3))
    import anim_life
    fz = []
    report = anim_life.motion_report(spec, hz=hz, frozen_out=fz)
    frozen_parts = sorted(p for p, (ms, _) in report.items() if ms >= 100)
    return {
        "rig": rig, "version": spec.get("version", 1), "parts": parts,
        "geo": {p: {"size": GEO[rig]["parts"][p][3], "shape": GEO[rig]["parts"][p][4]} for p in parts},
        "hz": hz, "frames": frames, "contact": contact,
        "markers": [{"name": m["name"], "t": round(m["f"] / fps, 4)} for m in spec.get("markers", [])],
        "length": round(L / fps, 4), "loop": bool(spec.get("loop")), "priority": spec.get("priority"),
        "history": spec.get("history", []), "notes": spec.get("notes", ""),
        "lint": [[lvl, msg] for lvl, msg in A.lint(spec)],
        "skippedParts": skipped,
        "frozen": [len(x) for x in fz[:len(frames)]] + [0] * max(0, len(frames) - len(fz)),
        "frozenParts": {p: report[p][0] for p in frozen_parts},
        "longestStillMs": max(ms for ms, _ in report.values()) if report else 0,
    }


def ground_pass(spec, frames, target=0.0, root=None):
    """Shift the root (R15 LowerTorso / R6 Torso) offset at the given key frames so the lowest sole sits at `target`
    (0 = planted, >0 = airborne clearance). frames: list of frames, or {frame: target}. Returns {frame: delta}."""
    rig = spec["rig"].upper()
    root = root or ("LowerTorso" if rig == "R15" else "Torso")
    targets = frames if isinstance(frames, dict) else {f: target for f in frames}
    deltas = {}
    for f, tgt in targets.items():
        low = min(sole_y(rig, fk(spec, rig, f)).values())
        d = tgt - low
        for k in spec["tracks"][root]:
            if abs(k["f"] - f) < 1e-6:
                p = list(k.get("p", [0, 0, 0]))
                p[1] = round(p[1] + d, 4)
                k["p"] = p
                deltas[f] = round(d, 3)
                break
        else:
            raise SystemExit(f"ground_pass: no {root} key at f{f}")
    spec.setdefault("history", []).append("ground pass (anim_preview.ground_pass): " + ", ".join(f"f{f}{d:+.2f}" for f, d in deltas.items()))
    return deltas


def ground_fill(spec, f_from=0.0, f_to=None, tol=0.03, max_keys=8, root=None):
    """Between keys the root's easing and the legs' easing can disagree and a foot dips through the floor. Scan
    [f_from, f_to] every half frame; at the worst dip insert a root key (current evaluated pose) grounded to 0;
    repeat until no dip > tol. Returns inserted frames."""
    rig = spec["rig"].upper()
    root = root or ("LowerTorso" if rig == "R15" else "Torso")
    f_to = A.length(spec) if f_to is None else f_to
    added = []
    for _ in range(max_keys):
        worst, wf = -tol, None
        f = f_from
        while f <= f_to + 1e-9:
            low = min(sole_y(rig, fk(spec, rig, f)).values())
            if low < worst:
                worst, wf = low, f
            f += 0.5
        if wf is None:
            break
        keys = spec["tracks"][root]
        if any(abs(k["f"] - wf) < 1e-6 for k in keys):  # already a key: just lift it
            ground_pass(spec, [wf], root=root)
            spec["history"].pop()
        else:
            rot, off = A.eval_track(spec, keys, wf)
            k = A.mkkey(wf, rot, off, "Linear", "InOut")
            k["p"] = [round(x, 4) for x in off]
            k["fl"] = 1  # computed key (continues the motion), not an authored pose
            keys.append(k)
            keys.sort(key=lambda k: k["f"])
            ground_pass(spec, [wf], root=root)
            spec["history"].pop()
        added.append(wf)
    if added:
        spec.setdefault("history", []).append("ground fill (anim_preview.ground_fill): root keys at " + ", ".join(f"f{x:g}" for x in added))
    return added


def ref_sheet(gif, out_path, cell=(200, 220), crop=(56, 8, 456, 448), cols=10):
    from PIL import Image
    im = Image.open(gif)
    n = im.n_frames
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell[0], rows * cell[1]))
    durs = []
    for i in range(n):
        im.seek(i)
        durs.append(im.info.get("duration", 33))
        fr = im.convert("RGB").crop(crop).resize(cell)
        sheet.paste(fr, ((i % cols) * cell[0], (i // cols) * cell[1]))
    sheet.save(out_path, "JPEG", quality=74, optimize=True)
    return {"n": n, "cols": cols, "cell": list(cell), "fps": round(1000 * n / sum(durs), 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hz", type=int, default=60)
    ap.add_argument("--clip", action="append", required=True, help='"ID|label|spec.json,spec.json|ref.gif-or-empty"')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    clips = []
    for c in a.clip:
        cid, label, specs, ref = (c.split("|") + [""])[:4]
        entry = {"id": cid, "label": label, "variants": []}
        for sp in filter(None, specs.split(",")):
            spec = A.load(sp)
            b = bake(spec, a.hz)
            b["file"] = os.path.basename(sp)
            entry["variants"].append(b)
            lo = min(b["contact"])
            print(f"{cid} {b['file']}: {len(b['frames'])} frames, lowest sole {lo:+.3f} studs")
            if b["skippedParts"]:
                print(f"  note: no preview geometry for extra joints {', '.join(b['skippedParts'])} (skipped in FK)")
        if ref:
            meta = ref_sheet(ref, os.path.join(a.out, f"ref_{cid}.jpg"))
            entry["ref"] = dict(meta, src=f"ref_{cid}.jpg")
        clips.append(entry)
    json.dump({"clips": clips}, open(os.path.join(a.out, "data.json"), "w"), separators=(",", ":"))
    print("wrote", os.path.join(a.out, "data.json"), f"{os.path.getsize(os.path.join(a.out, 'data.json')) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
