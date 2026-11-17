"""Scan every animation reference + recreation and regenerate the AUTO section of Animation_Pattern_Library.

Usage:  python kit/scripts/anim_patterns.py --vault V        (or set ANIMSMITH_VAULT)
Reads:   11_ASSET_LIBRARY/Animation/**/ANIM-*.md        (asset cards: category, rig_source, style, status)
         11_ASSET_LIBRARY/_media/anim/<id>/analysis/numbers.json   (reference timing measured by anim_analyze; the legacy
                                                              _media/frames/<id>/analysis.json is read when that is missing)
         11_ASSET_LIBRARY/_media/anim/<id>/iterations.json (feedback-loop scores from anim_compare; legacy _media/frames/<id>/ too)
         11_ASSET_LIBRARY/Animation/_specs/<id>/<id>_v###.json (the latest AnimSpec)
Writes:  the block between <!-- AUTO:BEGIN --> and <!-- AUTO:END --> in Animation_Pattern_Library.md.
The hand-written "Observed patterns" section of that note is Claude's job — this script only supplies numbers.
"""
from __future__ import annotations

import glob
import json
import os
import re
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_rig as R  # noqa: E402
import anim_spec as S  # noqa: E402

# Set by main() from --vault / ANIMSMITH_VAULT; never hard-coded.
ROOT = LIB = MEDIA = FRAMES = SPECS = NOTE = ""


def _resolve_vault(arg):
    try:
        from animlib import resolve_vault
    except ImportError:
        v = (arg or os.environ.get("ANIMSMITH_VAULT", "")).strip().strip('"').strip("'").strip()
        if not v or not os.path.isdir(os.path.join(v, "11_ASSET_LIBRARY")):
            raise SystemExit("no vault: pass --vault <dir> or set ANIMSMITH_VAULT to a folder that contains 11_ASSET_LIBRARY")
        return v
    return str(resolve_vault(arg))


def set_vault(vault):
    global ROOT, LIB, MEDIA, FRAMES, SPECS, NOTE
    ROOT = str(vault)
    LIB = os.path.join(ROOT, "11_ASSET_LIBRARY")
    MEDIA = os.path.join(LIB, "_media", "anim")        # new layout, one folder per id
    FRAMES = os.path.join(LIB, "_media", "frames")     # legacy layout
    SPECS = os.path.join(LIB, "Animation", "_specs")
    NOTE = os.path.join(LIB, "Animation_Pattern_Library.md")


def media_json(aid, new_rel, legacy_name):
    """Load <media>/<id>/<new_rel> else the legacy <frames>/<id>/<legacy_name> (None if neither exists)."""
    for p in (os.path.join(MEDIA, aid, *new_rel), os.path.join(FRAMES, aid, legacy_name)):
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return None


def analysis_for(aid):
    """Old-style analysis dict (summary, keypose_candidates, blur_or_smear, fps) from either file layout."""
    old = media_json(aid, ("analysis.json",), "analysis.json")
    if old:
        return old
    nj = media_json(aid, ("analysis", "numbers.json"), "numbers.json")
    if not nj:
        return None
    e = nj.get("energy") or []
    thr = 0.08
    moving = [i for i, v in enumerate(e) if v >= thr]
    n = nj.get("frames") or len(e)
    return {"fps": nj.get("fps_analysis") or 60.0,
            "summary": {"frames": n, "duration_s": nj.get("duration_s"),
                        "first_motion_frame": moving[0] + 1 if moving else None,
                        "fastest_frame": (e.index(max(e)) + 1) if e else None,
                        "settle_frame": moving[-1] + 1 if moving else None,
                        "hold_frames_total": sum(b - a + 1 for a, b in nj.get("holds", []))},
            "keypose_candidates": nj.get("keypose_candidates", []), "blur_or_smear": nj.get("smears", [])}


def frontmatter(path):
    t = open(path, encoding="utf-8").read()
    if not t.startswith("---"):
        return {}
    fm = t.split("---", 2)[1]
    out = {}
    for line in fm.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*?)\s*(#.*)?$", line)
        if m:
            out[m.group(1)] = m.group(2).strip('"')
    out["tags"] = re.findall(r"-\s+([a-z]+/[a-z0-9-]+)", fm)
    return out


def med(v):
    v = [x for x in v if x is not None]
    return round(st.median(v), 1) if v else "—"


def latest_spec(aid):
    files = sorted(glob.glob(os.path.join(SPECS, aid, f"{aid}_v*.json")))
    return (json.load(open(files[-1], encoding="utf-8")), len(files)) if files else (None, 0)


def spec_stats(spec):
    fps = spec.get("fps", 60)
    T = spec["tracks"]
    keys = [k for ks in T.values() for k in ks]
    eases = {}
    for k in keys:
        e = f"{k.get('e', 'CubicV2')}/{k.get('d', 'InOut')}"
        eases[e] = eases.get(e, 0) + 1
    torso = sorted({k["f"] for p in S.TORSO for k in T.get(p, [])})
    lags = []
    for p in S.EXTREMITIES:
        for k in T.get(p, []):
            prior = [f for f in torso if f <= k["f"]]
            if prior and k["f"] - prior[-1] > 0:
                lags.append((k["f"] - prior[-1]) * 60 / fps)
    detach = max((max(abs(x) for x in k["p"]) for k in keys if "p" in k), default=0)
    peak = 0.0
    L = int(S.length(spec))
    prev = {p: S.eval_track(spec, ks, 0)[0] for p, ks in T.items()}
    for f in range(1, L + 1):
        for p, ks in T.items():
            cur = S.eval_track(spec, ks, f)[0]
            peak = max(peak, R.angle_between(prev[p], cur) * 60 / fps)
            prev[p] = cur
    m = {x["name"]: x["f"] * 60 / fps for x in spec.get("markers", [])}
    return {"keys": len(keys), "eases": eases, "lag60": med(lags), "detach": round(detach, 2), "peak": round(peak),
            "startup60": m.get("HitStart"), "len60": round(L * 60 / fps)}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", help="vault folder (else ANIMSMITH_VAULT)")
    a = ap.parse_args(argv)
    set_vault(_resolve_vault(a.vault))
    rows, cat_stats, ease_total = [], {}, {}
    cards = sorted(glob.glob(os.path.join(LIB, "Animation", "**", "ANIM-*.md"), recursive=True))
    for card in cards:
        aid = os.path.basename(card)[:-3]
        fm = frontmatter(card)
        cat = next((t.split("/")[1] for t in fm.get("tags", []) if t.startswith("asset/") and t != "asset/animation"), "?")
        an = analysis_for(aid)
        its = media_json(aid, ("iterations.json",), "iterations.json") or []
        spec, nver = latest_spec(aid)
        r = {"id": aid, "cat": cat, "rig": fm.get("rig_source", "?"), "style": next((t.split("/")[1] for t in fm.get("tags", []) if t.startswith("style/")), "?")}
        if an:
            s, fps = an["summary"], an["fps"]
            ms = 1000 / fps
            fm0, fp, fs = s["first_motion_frame"], s["fastest_frame"], s["settle_frame"]
            r["dur"] = s["duration_s"]
            r["antic_ms"] = round((fp - fm0) * ms) if fm0 and fp else None
            r["follow_ms"] = round((fs - fp) * ms) if fs and fp else None
            r["hold_pct"] = round(100 * s["hold_frames_total"] / max(s["frames"], 1))
            r["keyposes"] = len(an["keypose_candidates"])
            r["smears"] = len(an["blur_or_smear"])
        if its:
            r["iters"] = len(its)
            r["best"] = max(e["score"] for e in its)
            r["trend"] = " → ".join(str(round(e["score"])) for e in its[-4:])
        if spec:
            ss = spec_stats(spec)
            r.update({"versions": nver, **{k: ss[k] for k in ("keys", "lag60", "detach", "peak", "startup60", "len60")}})
            for e, n in ss["eases"].items():
                ease_total[e] = ease_total.get(e, 0) + n
        rows.append(r)
        c = cat_stats.setdefault(cat, {"antic": [], "follow": [], "hold": [], "lag": [], "detach": [], "best": []})
        c["antic"].append(r.get("antic_ms"))
        c["follow"].append(r.get("follow_ms"))
        c["hold"].append(r.get("hold_pct"))
        c["lag"].append(r.get("lag60") if isinstance(r.get("lag60"), (int, float)) else None)
        c["detach"].append(r.get("detach"))
        c["best"].append(r.get("best"))

    g = lambda r, k: "—" if r.get(k) in (None, "") else r.get(k)  # noqa: E731
    out = ["<!-- AUTO:BEGIN — generated by kit/scripts/anim_patterns.py; do not edit by hand -->", ""]
    out.append(f"_{len(rows)} animation references scanned._")
    out.append("")
    out.append("### Per reference")
    out.append("| Asset | Cat | Rig src | Style | Len s | Anticipation ms | Follow-through ms | Hold % | Key poses | Smear frames | Spec v | Keys | Limb lag f@60 | Max detach studs | Peak °/f@60 | Iters | Best | Trend |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        out.append(f"| [[{r['id']}]] | {r['cat']} | {r['rig']} | {r['style']} | {g(r, 'dur')} | {g(r, 'antic_ms')} | {g(r, 'follow_ms')} | {g(r, 'hold_pct')} | "
                   f"{g(r, 'keyposes')} | {g(r, 'smears')} | {g(r, 'versions')} | {g(r, 'keys')} | {g(r, 'lag60')} | {g(r, 'detach')} | {g(r, 'peak')} | "
                   f"{g(r, 'iters')} | {g(r, 'best')} | {g(r, 'trend')} |")
    out.append("")
    out.append("### Per category (medians)")
    out.append("| Category | n | Anticipation ms | Follow-through ms | Follow/antic | Hold % | Limb lag f@60 | Detach studs | Best score |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for cat, c in sorted(cat_stats.items()):
        a, f = med(c["antic"]), med(c["follow"])
        ratio = round(f / a, 2) if isinstance(a, float) and isinstance(f, float) and a else "—"
        out.append(f"| {cat} | {len(c['antic'])} | {a} | {f} | {ratio} | {med(c['hold'])} | {med(c['lag'])} | {med(c['detach'])} | {med(c['best'])} |")
    out.append("")
    if ease_total:
        tot = sum(ease_total.values())
        out.append("### Easing used in recreations")
        out.append(", ".join(f"{e} {100 * n / tot:.0f}%" for e, n in sorted(ease_total.items(), key=lambda x: -x[1])))
        out.append("")
    out.append("<!-- AUTO:END -->")
    block = "\n".join(out)
    text = open(NOTE, encoding="utf-8").read()
    text = re.sub(r"<!-- AUTO:BEGIN.*?<!-- AUTO:END -->", lambda _: block, text, flags=re.S)
    open(NOTE, "w", encoding="utf-8").write(text)
    print(f"updated {os.path.relpath(NOTE, ROOT)} ({len(rows)} references)")


if __name__ == "__main__":
    main()
