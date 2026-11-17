"""Search the vault's animation references (ANIM-* cards, their Breakdowns and build notes) without building.

    python anim_find.py --vault VAULT "heavy overhead slam with hitstop"
    python anim_find.py "reload" --cat weapon --kind video --k 5
    python anim_find.py "" --cat loco                       # facets only: every matching card, by id
    python anim_find.py "dash" --json

Reads `11_ASSET_LIBRARY/Animation/<Cat>/ANIM-*.md`, `Breakdowns/Breakdown_<ID>.md` and, when present,
`Animation/_builds/<ID>*_Build_Notes.md`. Ranking is BM25F over the title, tags, other frontmatter, headings and
body text. Facets: --cat (the card's `category:` or the ID prefix), --style (`style/...` tags), --rig
(`rig_source:`), --kind (`kind:`). VAULT defaults to the ANIMSMITH_VAULT environment variable.
Each hit carries `snippet`: the best-matching line of its card, Breakdown or build notes (a matching timing-table
row is preferred), at most 160 characters; null for a facets-only search. Paths are printed OS-native.
Stdlib only, no network.
"""
import argparse
import glob
import json
import math
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from animlib import CATEGORIES, category_of  # noqa: E402

FIELDS = {"title": 4.0, "tags": 2.5, "meta": 1.0, "heads": 1.0, "body": 0.5}
K1, B = 1.2, 0.75
CARD_RE = re.compile(r"^ANIM-[A-Z]+-\d{4,}$")
PREFIX_CAT = {v["prefix"]: k for k, v in CATEGORIES.items()}

STOP = set("""a an and are as at be but by can do does for from get got have how i if in into is it its like
make my me of on or so that the then there this to too up use using want way what when where which while
why will with without you your we our not no just also should would could any some all one
reference references ref refs card breakdown fill todo analyst anim animation animations""".split())

# everyday words -> vocabulary the cards and Breakdowns use (query only, weight 0.4)
SYN = {
    "punch": ["strike", "jab", "hook"], "hit": ["strike", "contact", "impact"], "kick": ["strike"],
    "slash": ["swing", "strike"], "swing": ["slash", "arc"], "pause": ["hitstop", "hold"],
    "freeze": ["hitstop", "hold"], "hitstop": ["hitstop", "freeze"], "shake": ["shake", "camera"],
    "wind": ["anticipation"], "windup": ["anticipation"], "charge": ["anticipation"],
    "walk": ["loco", "cycle"], "run": ["loco", "cycle", "sprint"], "sprint": ["run"], "dash": ["dodge", "loco"],
    "dodge": ["dash"], "roll": ["dodge"], "jump": ["loco", "air"], "idle": ["loop", "stance"],
    "loop": ["cycle"], "gun": ["weapon", "recoil", "reload"], "shoot": ["recoil", "fire"],
    "fire": ["recoil"], "reload": ["reload", "magazine"], "sword": ["weapon", "slash"],
    "knockdown": ["reaction", "fall"], "flinch": ["reaction", "hit"], "getup": ["reaction", "rise"],
    "stagger": ["reaction"], "spell": ["ability", "cast"], "cast": ["ability"], "door": ["world"],
    "anime": ["anime", "snappy"], "snappy": ["snappy", "anime"], "heavy": ["weighty", "slam"],
    "weighty": ["heavy"], "realistic": ["realistic"],
}


def stem(w):
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", "")):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + rep
    if len(w) > 4 and w.endswith("es") and w[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return w[:-2]
    if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(s):
    out = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]*|\d+", s or ""):
        low = word.lower()
        if low in STOP or len(low) < 2:
            continue
        out.append(stem(low))
        parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", word)
        if len(parts) > 1:
            out += [stem(p.lower()) for p in parts if p.lower() not in STOP and len(p) > 1]
    return out


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def strip_comment(v):
    q = None
    for i, ch in enumerate(v):
        if ch in "\"'":
            q = None if q == ch else (q or ch)
        elif ch == "#" and q is None and (i == 0 or v[i - 1].isspace()):
            return v[:i].rstrip()
    return v.rstrip()


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        try:
            return json.loads(v) if v[0] == '"' else v[1:-1]
        except ValueError:
            return v[1:-1]
    return v


def parse_frontmatter(text):
    m = re.match(r"^﻿?---\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", text, re.S)
    if not m:
        return {}, text
    fm, key = {}, None
    for raw in m.group(1).splitlines():
        line = strip_comment(raw)
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s*(.*)$", line)
        if item and key is not None:
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(unquote(item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                fm[key] = [unquote(x) for x in val[1:-1].split(",") if x.strip()]
            else:
                fm[key] = unquote(val) if val else []
    return fm, text[m.end():]


def as_list(v):
    return v if isinstance(v, list) else ([v] if v else [])


def first(v):
    return v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else "")


def clean_body(body):
    body = re.sub(r"\{\{[^}]*\}\}", " ", body)
    body = re.sub(r"TODO\(analyst\)[^\n]*", " ", body)        # the template's instructions aren't content
    body = re.sub(r"!\[\[[^\]]*\]\]", " ", body)
    body = re.sub(r"```.*?```", lambda c: c.group(0)[:600], body, flags=re.S)
    return body


def clean_line(x):
    """One body line as plain text for a snippet: wikilinks as their text, no bold/heading/quote markers; table
    separators and code fences dropped."""
    x = x.strip()
    if not x or x.startswith("```") or re.fullmatch(r"[\s:|\-]+", x):
        return ""
    x = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", x)
    x = re.sub(r"^(?:#+|>)\s*", "", x).replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", x).strip()


def is_timing_row(line):
    """A table row carrying numbers (frames, ms, seconds): the most useful thing to quote."""
    return line.startswith("|") and line.count("|") >= 3 and bool(re.search(r"\d", line))


SNIPPET_MAX = 160


def snippet(lines, terms, limit=SNIPPET_MAX):
    """(critic r2) The line that best matches the query (most query weight; a matching timing-table row wins over
    prose), cut to `limit` characters around its first match. None for a facets-only search."""
    if not terms:
        return None
    best, best_row = None, None
    for i, ln in enumerate(lines):
        toks = set(tokens(ln))
        sc = sum(w for t, w in terms.items() if t in toks)
        if sc <= 0:
            continue
        key = (sc, -len(ln) if len(ln) > limit else 0, -i)
        if best is None or key > best[0]:
            best = (key, ln)
        if is_timing_row(ln) and (best_row is None or key > best_row[0]):
            best_row = (key, ln)
    pick = (best_row or best or (None, None))[1]
    if not pick:
        return None
    if len(pick) <= limit:
        return pick
    low = pick.lower()
    pos = min([p for p in (low.find(t) for t in terms) if p >= 0] or [0])
    start = max(0, min(pos - 40, len(pick) - (limit - 2)))
    out = pick[start:start + limit - (1 if start else 0) - 1]
    return ("…" if start else "") + out.rstrip() + "…"


def styles_of(tags):
    out = []
    for t in tags:
        t = t.strip().lstrip("#")
        if t.lower().startswith("style/") and "{{" not in t:
            out.append(t.split("/", 1)[1].lower())
    return out


def find_sheets(lib, cid):
    d = os.path.join(lib, "_media", "anim", cid, "sheets")
    found = []
    for ext in ("jpg", "png", "jpeg", "webp"):
        found += glob.glob(os.path.join(d, "*." + ext))
    return sorted(os.path.normpath(f) for f in found)


def load_docs(vault):
    lib = os.path.join(vault, "11_ASSET_LIBRARY")
    paths = sorted(set(glob.glob(os.path.join(lib, "Animation", "*", "ANIM-*.md"))))
    docs = []
    for path in paths:
        cid = os.path.basename(path)[:-3]
        if not CARD_RE.match(cid):
            continue
        fm, body = parse_frontmatter(read(path))
        bpath = os.path.join(lib, "Breakdowns", "Breakdown_%s.md" % cid)
        bfm, bbody = parse_frontmatter(read(bpath)) if os.path.isfile(bpath) else ({}, "")
        builds = sorted(glob.glob(os.path.join(lib, "Animation", "_builds", cid + "*_Build_Notes.md")))
        btext = "\n".join(parse_frontmatter(read(b))[1] for b in builds)
        tags = [t for t in as_list(fm.get("tags")) + as_list(bfm.get("tags")) if "{{" not in t]
        h1 = re.search(r"^#\s+(.+)$", body, re.M)
        title = h1.group(1).strip() if h1 else cid
        title = re.sub(r"^" + re.escape(cid) + r"\s*[—\-:]+\s*", "", title).strip() or cid
        cat = category_of(first(fm.get("category"))) or PREFIX_CAT.get(cid.rsplit("-", 1)[0])
        meta_vals = []
        for k in ("aliases", "kind", "category", "rig_source", "scale", "provenance", "intent", "user_note",
                  "source_file"):
            meta_vals += [v for v in as_list(fm.get(k)) if "{{" not in v]
        text = clean_body(body) + "\n" + clean_body(bbody) + "\n" + clean_body(btext)
        heads = re.findall(r"^#{1,4} +(.+)$", text, re.M)
        lines = [ln for ln in (clean_line(x) for x in text.splitlines()) if ln]
        fields = {"title": tokens(title),
                  "tags": tokens(" ".join(t.replace("/", " ").replace("-", " ") for t in tags)),
                  "meta": tokens(" ".join(meta_vals)), "heads": tokens(" ".join(heads)), "body": tokens(text)}
        docs.append({
            "id": cid, "title": title, "card": os.path.normpath(path),
            "breakdown": os.path.normpath(bpath) if os.path.isfile(bpath) else None,
            "builds": [os.path.normpath(b) for b in builds], "lines": lines, "category": cat, "kind": (first(fm.get("kind")) or "").lower() or None,
            "rig": (first(fm.get("rig_source")) or "").lower() or None, "styles": styles_of(tags),
            "breakdown_status": first(fm.get("breakdown_status")) or None,
            "media_dir": os.path.normpath(os.path.join(lib, "_media", "anim", cid)) if os.path.isdir(
                os.path.join(lib, "_media", "anim", cid)) else None,
            "sheets": find_sheets(lib, cid),
            "tf": {f: Counter(v) for f, v in fields.items()}, "len": {f: len(v) for f, v in fields.items()},
        })
    return docs


def query_terms(q):
    terms = Counter(tokens(q))
    for w in re.findall(r"[a-z]+", (q or "").lower()):
        for s in SYN.get(w, []):
            terms[stem(s)] += 0.4
    return terms


def bm25f(terms, docs):
    n = len(docs)
    avg = {f: (sum(d["len"][f] for d in docs) / n) or 1 for f in FIELDS}
    df = Counter()
    for d in docs:
        for t in {t for f in FIELDS for t in d["tf"][f]}:
            df[t] += 1
    scores = []
    for d in docs:
        s = 0.0
        for t, qw in terms.items():
            if not df[t]:
                continue
            tf = sum(w * d["tf"][f].get(t, 0) / (1 - B + B * d["len"][f] / avg[f]) for f, w in FIELDS.items())
            if tf:
                s += qw * math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf / (K1 + tf)
        scores.append(s)
    return scores


def _flt(v):
    return [x.strip().lower().split("/", 1)[-1] for x in (v or "").split(",") if x.strip()]


def search(vault, query, cat=None, style=None, rig=None, kind=None, k=5):
    docs = load_docs(vault)
    cats = [category_of(c) or c for c in _flt(cat)]
    styles, rigs, kinds = _flt(style), _flt(rig), _flt(kind)
    keep = [d for d in docs
            if (not cats or d["category"] in cats) and (not styles or set(styles) & set(d["styles"]))
            and (not rigs or (d["rig"] or "") in rigs) and (not kinds or (d["kind"] or "") in kinds)]
    terms = query_terms(query)
    scores = bm25f(terms, keep) if (keep and terms) else [0.0] * len(keep)
    results = []
    for d, s in zip(keep, scores):
        if terms and s <= 0:
            continue
        results.append({"id": d["id"], "title": d["title"], "score": round(s, 3), "category": d["category"],
                        "kind": d["kind"], "rig": d["rig"], "styles": d["styles"],
                        "breakdown_status": d["breakdown_status"], "card": d["card"], "breakdown": d["breakdown"],
                        "builds": d["builds"], "media_dir": d["media_dir"],
                        "sheet": d["sheets"][0] if d["sheets"] else None,
                        "snippet": snippet(d["lines"], terms)})
    if terms:
        results.sort(key=lambda r: (-r["score"], r["id"]))
        results = results[: max(1, k)]
    else:
        results.sort(key=lambda r: r["id"])
    return results, len(docs), len(keep)


def main(argv=None):
    ap = argparse.ArgumentParser(description="BM25 search over the vault's animation cards and Breakdowns.")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--vault", default=os.environ.get("ANIMSMITH_VAULT"))
    ap.add_argument("--cat", help="category: " + ", ".join(CATEGORIES))
    ap.add_argument("--style", help="style tag slug(s), comma-separated (anime, realistic, snappy, weighty ...)")
    ap.add_argument("--rig", help="r6, r15 or unknown")
    ap.add_argument("--kind", help="video, gif, images, roblox")
    ap.add_argument("--k", "-k", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    vault = (a.vault or "").strip().strip('"')
    if not vault or not os.path.isdir(os.path.join(vault, "11_ASSET_LIBRARY")):
        msg = "vault not found: pass --vault (or set ANIMSMITH_VAULT) to the folder that holds 11_ASSET_LIBRARY"
        print(json.dumps({"error": msg}) if a.json else msg, file=sys.stdout if a.json else sys.stderr)
        return 2
    bad = [c for c in _flt(a.cat) if not category_of(c)]
    if bad:
        msg = "unknown --cat %s (use one of: %s)" % (", ".join(bad), ", ".join(CATEGORIES))
        print(json.dumps({"error": msg, "categories": list(CATEGORIES)}) if a.json else msg,
              file=sys.stdout if a.json else sys.stderr)
        return 2
    results, total, kept = search(vault, a.query, a.cat, a.style, a.rig, a.kind, a.k)
    if a.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0
    if total == 0:
        print("No animation cards in the vault yet. Add references with /anim learn.")
        return 0
    if not results:
        why = "no card has those facets" if kept == 0 else "no card matches those words"
        print("No matches (%s; %d card%s searched)." % (why, total, "" if total == 1 else "s"))
        return 0
    for i, r in enumerate(results, 1):
        print("%d. %s  %s  (score %.2f; %s, %s, breakdown %s)" % (i, r["id"], r["title"], r["score"],
                                                                 r["category"], r["kind"] or "?",
                                                                 r["breakdown_status"] or "?"))
        if r["snippet"]:
            print("   match: %s" % r["snippet"])
        print("   card: %s" % r["card"])
        if r["breakdown"]:
            print("   breakdown: %s" % r["breakdown"])
        if r["media_dir"]:
            print("   media: %s" % r["media_dir"])
        if r["sheet"]:
            print("   sheet: %s" % r["sheet"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
