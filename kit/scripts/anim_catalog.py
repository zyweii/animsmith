#!/usr/bin/env python3
"""Offline catalogue of a Roblox animation file (.rbxm / .rbxmx / .rbxl / .rbxlx) - nothing in it ever runs.

    python kit/scripts/anim_catalog.py <file> [--out dir] [--json]

For every KeyframeSequence in the file it walks Keyframe (Time) -> nested Pose tree (CFrame as the RAW matrix, EasingStyle,
EasingDirection, Weight) and KeyframeMarker, and converts it to an AnimSpec v1 dict (REL eulers through anim_rig; rig guessed
R15/R6 from the part names; 60 fps; keys at the keyframe times rounded to frames; Weight-0 container poses skipped).
Animation instances are listed with their AnimationId only (no content is fetched).

Every script in the file is scanned (never executed, never copied out) for the markers backdoors leave behind: remote require,
getfenv/setfenv, loadstring, long escape strings, webhooks, InsertService/GetObjects, http URLs, "SaveInstance"/"Decompiled" banners.

As a module:  extract(path) -> {"scan": {"scripts": n, "suspicious": [...]}, "sequences": [...], "animations": [...]}
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_rig as R  # noqa: E402
import anim_spec as A  # noqa: E402
import rbxdump as rd  # noqa: E402

SCRIPT_CLASSES = {"Script", "LocalScript", "ModuleScript", "CoreScript"}
FPS = 60
PRIORITY_NAME = {v: k for k, v in A.PRIORITY.items()}

# (flag, regex): the same family vfxmith's pack scanner looks for, plus the extra ones asked for animation files
SUSPICIOUS = [
    ("remote_require", re.compile(r"require\s*\(\s*(?:\d{5,}|game\s*[:.]\s*GetService\s*\(\s*[\"']InsertService)")),
    ("getfenv_setfenv", re.compile(r"\b[gs]etfenv\b")),
    ("loadstring", re.compile(r"\bloadstring\b")),
    ("long_escape_string", re.compile(r"(?:\\\d{2,3}){20,}")),
    ("webhook", re.compile(r"(?:discord(?:app)?\.com|webhook\.site|hooks\.slack\.com)/(?:api/)?webhooks?", re.I)),
    ("insertservice_getobjects", re.compile(r"InsertService|:GetObjects\s*\(|\bGetObjects\b")),
    ("http_url", re.compile(r"https?://", re.I)),
    ("http_service", re.compile(r"HttpService|\bHttpGet\b|\bPostAsync\b|\bRequestAsync\b")),
    ("decompiler_banner", re.compile(r"SaveInstance|Decompiled|decompiled by|Synapse|Krnl|ScriptWare", re.I)),
]


# ------------------------------------------------------------------ scan

def scan_scripts(insts, idx):
    """Flag suspicious scripts by regex over their Source text. Pure string matching: nothing is executed or written out."""
    scripts = [o for o in insts if o["class"] in SCRIPT_CLASSES]
    sus = []
    for o in scripts:
        src = o["props"].get("Source")
        src = src if isinstance(src, str) else ""
        flags = sorted(flag for flag, rx in SUSPICIOUS if rx.search(src))
        # any long run of escaped bytes or very long single line hints at obfuscation even when the regexes miss it
        if src and max((len(line) for line in src.splitlines()), default=0) > 4000 and "long_line" not in flags:
            flags.append("long_line")
        if flags:
            sus.append({"path": rd.path_of(o, idx), "class": o["class"], "name": o["name"], "flags": flags, "length": len(src)})
    return {"scripts": len(scripts), "suspicious": sus}


# ------------------------------------------------------------------ decode helpers

def _rot_from_props(cf):
    """Pose CFrame prop -> (rotation rows, position). 12 numbers = raw matrix; 6 numbers = rbxdump's rounded YXZ euler (fallback)."""
    if not cf:
        return [row[:] for row in R.IDENTITY], [0.0, 0.0, 0.0]
    cf = list(cf)
    if len(cf) >= 12:
        return [cf[3:6], cf[6:9], cf[9:12]], cf[0:3]
    if len(cf) >= 6:  # ToOrientation order: R = Ry * Rx * Rz
        rx, ry, rz = (math.radians(v) for v in cf[3:6])
        return R.mat_mul(R.rot_y(ry), R.mat_mul(R.rot_x(rx), R.rot_z(rz))), cf[0:3]
    return [row[:] for row in R.IDENTITY], cf[0:3] + [0.0] * (3 - len(cf[0:3]))


def _num(v, default=0.0):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _enum(v, names, default):
    return names[v] if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(names) else default


def guess_rig(names):
    r15 = {"UpperTorso", "LowerTorso", "RightUpperArm", "LeftUpperArm", "RightUpperLeg", "LeftUpperLeg", "RightHand", "LeftHand",
           "RightLowerArm", "LeftLowerArm", "RightFoot", "LeftFoot"}
    r6 = {"Torso", "Right Arm", "Left Arm", "Right Leg", "Left Leg"}
    n15, n6 = len(names & r15), len(names & r6)
    if n15 == n6 == 0:
        return "R15"
    return "R15" if n15 >= n6 else "R6"


def guess_fps(times):
    """Smallest of 24/30/60/120 at which every key time lands on a whole frame; 60 when none does."""
    ts = [t for t in times if t > 0]
    for fps in (24, 30, 60, 120):
        if ts and all(abs(t * fps - round(t * fps)) < 0.02 for t in ts):
            return fps
    return 60


def _children(o, idx, cls=None):
    return [idx[c] for c in o["children"] if c in idx and (cls is None or idx[c]["class"] == cls)]


def _walk_poses(pose, idx, parent_name, out):
    """Depth-first; out gets (name, parent_pose_name, props)."""
    out.append((pose["name"], parent_name, pose["props"]))
    for c in _children(pose, idx, "Pose"):
        _walk_poses(c, idx, pose["name"], out)


def decode_sequence(kfs, idx):
    """KeyframeSequence instance -> dict (raw keyframes) with parts, markers and the converted AnimSpec."""
    kf_rows = []
    for kf in _children(kfs, idx, "Keyframe"):
        t = _num(kf["props"].get("Time"))
        poses = []
        for root in _children(kf, idx, "Pose"):
            _walk_poses(root, idx, None, poses)
        markers = [(m["name"], m["props"].get("Value", "") if isinstance(m["props"].get("Value", ""), str) else str(m["props"].get("Value"))) for m in _children(kf, idx, "KeyframeMarker")]
        kf_rows.append((t, poses, markers))
    kf_rows.sort(key=lambda r: r[0])
    length_s = max((r[0] for r in kf_rows), default=0.0)
    times = [r[0] for r in kf_rows]
    names = {n for _, poses, _ in kf_rows for n, _, p in poses if _num(p.get("Weight"), 1.0) > 0 and n != "HumanoidRootPart"}
    rigname = guess_rig(names)
    rig = R.load_rig(rigname)
    spec = {"id": f"IMPORT-{re.sub(r'[^A-Za-z0-9_-]+', '_', kfs['name'] or 'sequence')}", "version": 1, "name": kfs["name"] or "sequence",
            "rig": rigname, "space": "rel", "fps": FPS, "loop": bool(kfs["props"].get("Loop", False)),
            "priority": PRIORITY_NAME.get(kfs["props"].get("Priority"), "Action"),
            "tracks": {}, "markers": [],
            "history": [f"cataloged from {kfs['name']} (anim_catalog)"]}
    keyed = {}  # part -> {frame: key}
    for t, poses, markers in kf_rows:
        f = round(t * FPS)
        for name, parent, p in poses:
            if _num(p.get("Weight"), 1.0) <= 0 or name == "HumanoidRootPart":
                continue  # container poses (Weight 0) only carry hierarchy
            if name not in rig["parts"]:
                par = parent if parent in rig["parts"] else rig["root"]
                rig = R.add_extra_joints(rig, {name: {"parent": par}})
                spec.setdefault("extra_joints", {})[name] = {"parent": par}
            rot, pos = _rot_from_props(p.get("CFrame"))
            rel, off = R.joint_to_rel(rig, name, rot, pos)
            style = _enum(p.get("EasingStyle"), A.STYLES, "Linear")
            direction = _enum(p.get("EasingDirection"), A.DIRS, "In")
            keyed.setdefault(name, {})[f] = A.mkkey(f, rel, off, style, direction)
        for mname, mval in markers:
            spec["markers"].append({"name": mname, "value": mval, "f": f})
    spec["tracks"] = {n: [ks[f] for f in sorted(ks)] for n, ks in keyed.items()}
    spec["length"] = round(length_s * FPS)
    fps_guess = guess_fps(times)
    return {
        "name": kfs["name"], "path_in_file": rd.path_of(kfs, idx), "length_s": round(length_s, 4), "fps_guess": fps_guess,
        "loop": spec["loop"], "priority": spec["priority"], "keyframes": len(kf_rows),
        "parts": sorted(spec["tracks"]), "markers": [dict(m) for m in spec["markers"]], "spec": spec,
    }


# ------------------------------------------------------------------ public API

def extract(path):
    res = rd.load(path, raw=True)
    insts = res[0] if isinstance(res, tuple) else res
    idx = rd.index(insts)
    out = {"file": os.path.basename(path), "scan": scan_scripts(insts, idx), "sequences": [], "animations": []}
    for o in insts:
        if o["class"] == "KeyframeSequence":
            out["sequences"].append(decode_sequence(o, idx))
        elif o["class"] == "Animation":
            aid = o["props"].get("AnimationId")
            aid = aid if isinstance(aid, str) else ""
            out["animations"].append({"name": o["name"], "path_in_file": rd.path_of(o, idx), "animation_id": aid,
                                      "asset_id": rd.asset_id(aid)})
    undecoded = sorted({u for o in insts for u in o["props"].get("__undecoded__", [])})
    if undecoded:
        out["undecoded_props"] = undecoded
    return out


def _safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s) or "sequence"


def write_out(result, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for i, s in enumerate(result["sequences"]):
        p = os.path.join(out_dir, f"{i + 1:02d}_{_safe_name(s['name'])}.spec.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(s["spec"], fh, indent=1)
        written.append(p)
    p = os.path.join(out_dir, "catalog.json")
    slim = dict(result, sequences=[{k: v for k, v in s.items() if k != "spec"} for s in result["sequences"]])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(slim, fh, indent=1)
    return written + [p]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--out", help="folder for one <n>_<name>.spec.json per sequence plus catalog.json")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    result = extract(a.file)
    written = write_out(result, a.out) if a.out else []
    if a.json:
        print(json.dumps(result, indent=1))
        return 0
    sc = result["scan"]
    print(f"{result['file']}: {len(result['sequences'])} KeyframeSequence, {len(result['animations'])} Animation, {sc['scripts']} script(s)")
    for s in result["sequences"]:
        print(f"  {s['name']}  [{s['spec']['rig']}] {s['length_s']}s fps~{s['fps_guess']} keyframes={s['keyframes']} "
              f"parts={len(s['parts'])} markers={[m['name'] for m in s['markers']]} loop={s['loop']} priority={s['priority']}")
    for an in result["animations"]:
        print(f"  Animation {an['name']}: {an['animation_id'] or '(no id)'}")
    if sc["suspicious"]:
        print(f"WARNING: {len(sc['suspicious'])} suspicious script(s) (not run, not copied):")
        for s in sc["suspicious"]:
            print(f"  {s['path']} ({s['class']}): {', '.join(s['flags'])}")
    elif sc["scripts"]:
        print("scripts: none matched the suspicious markers (still never run them blind)")
    for p in written:
        print("wrote", p)
    if result.get("undecoded_props"):
        print("note: could not decode properties:", ", ".join(result["undecoded_props"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
