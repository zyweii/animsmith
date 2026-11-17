"""animsmith anim_intake.py: file animation references into the vault (`/anim learn`, plan section 7.1).

    python anim_intake.py --vault V [--files F ...] [--category C] [--rig r6|r15|unknown] [--crop x,y,w,h]
                          [--trim a-b] [--provenance own|licensed|third-party] [--scale absolute|match]
                          [--gpu on|off] [--dry-run] [--json]
    python anim_intake.py --vault V --pack <ID> --json          the per-reference block of a filed ID
    python anim_intake.py --vault V --set-meta <ID> [--provenance P] [--scale S] [--json]
    python anim_intake.py --vault V --refile <ID> --category C [--dry-run] [--json]

Input: every file in VAULT/11_ASSET_LIBRARY/_inbox/anim/ and its per-category subfolders (_inbox/anim/<cat>/),
or --files. A sidecar note `<full name>.txt` or `<stem>.txt|.md` is the user's note (verbatim on the card).
Category: --category > the subfolder name > the note's first word when it is a category > skipped
("no category"; the skill asks the user). Categories: combat weapon ability loco world camera reaction.

A sidecar line `trim: <start>-<end>` (seconds, or m:ss) or --trim limits frames and analysis to that range (the
source is kept whole); it is recorded as `trim` in numbers.json. --provenance / --scale override what the note
implies, for every file in the run; --set-meta corrects a filed card. From the note: `own` only for an explicit,
un-negated claim ("my own", "mine", "I made/recorded/animated this", "my recording/animation/clip"); `licensed` for
mixamo / rokoko / actorcore / licensed / bought; a negation ("not mine") or any named source (youtube, tiktok,
another game, a game name, "ripped", "from ...") gives `third-party`. `scale: match` only for own work the note
wants copied faithfully ("match", "exactly", "1:1"), else `absolute`. A claim plus a source (or a bare "mine"
that isn't a claim) is filed third-party + absolute with `provenance_guess: "ambiguous"`: the skill asks
(`provenance_guess` is otherwise "clear", "no_signal" or "override"). Titles are plain text (no `[[ ]] | #`, at
most 60 characters, cut at a word); on the card the note's `[[`/`]]` become `⟦`/`⟧` (the JSON `user_note` is
verbatim). Two references cut from one clip are two
copies named `name.mp4`, `name-b.mp4`, `name-c.mp4` ... (a `_NN` ending marks a pose-sheet still instead).

Kinds: video (mp4 mov webm mkv avi), gif, images (png jpg jpeg webp; `name_01.png`, `name_02.png` ... = one
pose-sheet reference), roblox (rbxm rbxmx, decoded offline by anim_catalog.py: one card per KeyframeSequence),
data (fbx bvh glb: skipped until phase 4).

Per reference: _media/anim/<ID>/{source,frames,sheets,analysis/numbers.json + numbers_brief.json}, the card in
Animation/<Cat>/<ID>.md and Breakdowns/Breakdown_<ID>.md from the vault templates (only the {{...}} placeholders
are replaced; TODO(analyst) markers stay for the analyst), a hub line, an Asset_Library_Index row and
Animation/_specs/<ID>/. Inbox files are moved (copied, then deleted once filed); --files outside the inbox are
copied. The sidecar note is copied into source/ next to the original (then deleted from the inbox with it). A file
that fails is rolled back (only what this run made). Then build_mocs.py and validate_vault.py --folder
11_ASSET_LIBRARY run from the vault; only problems this run made count: the validator also runs once before the
first write, and problems a shared note (hub, Asset_Library_Index) already had are listed under `pre_existing` and
counted in `elsewhere` with problems in other notes; neither fails the run.

--dry-run writes nothing; when a video would decode on the GPU it checks the GPU once (animlib.gpu_check) and
reports `gpu_ok` (true / false / null when nothing was checked) and `gpu_reason`; false means a real run would exit
4 (those videos get would_fail with code gpu_failed).

A .rbxm/.rbxmx whose script scan flags anything is stored as source/<name>.quarantine (not a loadable extension)
and its card says so.

GPU first: video decode uses ffmpeg -hwaccel cuda. If the GPU path fails the run stops with exit 4 (reason
gpu_failed); --gpu off reruns on the CPU, only when the user says so. A file whose format NVDEC can't decode
(H.264 4:4:4 or 10-bit, ...) fails alone with reason nvdec_unsupported_format (the user decides on a CPU decode
of that file); a corrupt file fails alone with decode_errors. Every error result carries `code`.

Exit: 0 ok · 1 a file failed (rolled back, others filed) · 2 bad vault/templates · 3 validate problems ·
4 GPU failed. --json prints {"results": [...], "tools": {...}, "gpu": bool, ...}.
"""

import argparse
import datetime as _dt
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import animlib  # noqa: E402
import anim_analyze  # noqa: E402
from animlib import CATEGORIES, GpuError  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
GIF_EXT = {".gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
ROBLOX_EXT = {".rbxm", ".rbxmx"}
DATA_EXT = {".fbx", ".bvh", ".glb"}
NOTE_EXT = {".txt", ".md"}
CARD_TPL = "Template_Anim_Asset_Card.md"
BD_TPL = "Template_Anim_Breakdown.md"
HUB_END = "<!-- ANIM-CARDS:END -->"
INDEX_END = "<!-- ASSET-ROWS:END -->"
NO_ASSETS = "_No assets yet._"
SET_RX = re.compile(r"^(.*?)[_\- ](\d{1,3})$")
ANALYST_FRAMES = 6


def _today():
    return _dt.date.today().isoformat()


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


class Ctx:
    def __init__(self, vault):
        self.vault = Path(vault).resolve()
        self.lib = self.vault / "11_ASSET_LIBRARY"
        self.inbox = self.lib / "_inbox" / "anim"
        self.media = self.lib / "_media" / "anim"
        self.bddir = self.lib / "Breakdowns"
        self.specs = self.lib / "Animation" / "_specs"
        self.tpl = self.vault / "_meta" / "templates"
        self.index = self.lib / "Asset_Library_Index.md"

    def guard(self, path):
        if not _inside(path, self.lib):
            raise RuntimeError(f"refusing to write outside 11_ASSET_LIBRARY: {path}")
        return Path(path)

    def hub(self, cat):
        return self.lib / f"{CATEGORIES[cat]['hub']}.md"

    def card_path(self, cat, ID):
        return self.lib / CATEGORIES[cat]["folder"] / f"{ID}.md"


# ---------------------------------------------------------------- gather

CLASH_RX = re.compile(r"-([b-z])$")


def free_name(folder, name):
    """name, or name-b, name-c ... before the extension when it is taken in folder (never _2: a _NN ending marks a
    pose-sheet still)."""
    folder = Path(folder)
    if not (folder / name).exists():
        return name
    stem, ext = Path(name).stem, Path(name).suffix
    for c in "bcdefghijklmnopqrstuvwxyz":
        cand = f"{stem}-{c}{ext}"
        if not (folder / cand).exists():
            return cand
    raise RuntimeError(f"no free name for {name} in {folder}")


TITLE_MAX = 60


def plain_title(s, limit=TITLE_MAX):
    """(critic r2) A title safe for an H1, a hub line and an index row: no `[[`, `]]`, `|`, `#` or line breaks (they
    made wikilinks, split table cells or started headings), whitespace collapsed, at most `limit` characters cut at
    a word boundary."""
    s = str(s or "").replace("[[", " ").replace("]]", " ").replace("|", " ").replace("#", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        head = s[:limit + 1]
        cut = head.rsplit(" ", 1)[0] if " " in head else s[:limit]
        s = cut[:limit].rstrip(" ,;:.-—–")
    return s


def note_for_card(note):
    """The user's note as written on the card and Breakdown: verbatim except that it can't form a wikilink."""
    return None if note is None else str(note).replace("[[", "⟦").replace("]]", "⟧")


def _clean_title(stem):
    stem = CLASH_RX.sub("", stem)                    # clip-b.mp4 is a second cut of clip.mp4: same title
    s = re.sub(r"^\d{4}-\d{2}-\d{2}[_\- ]*", "", stem)
    s = plain_title(re.sub(r"[_\-]+", " ", s))
    return (s[:1].upper() + s[1:]) if s else "Animation reference"


def _kind_of(ext):
    if ext in VIDEO_EXT:
        return "video"
    if ext in GIF_EXT:
        return "gif"
    if ext in IMAGE_EXT:
        return "images"
    if ext in ROBLOX_EXT:
        return "roblox"
    if ext in DATA_EXT:
        return "data"
    return None


def _sidecar(folder, names, taken):
    for n in names:
        for ext in (".txt", ".md"):
            p = folder / (n + ext)
            if p.is_file() and p not in taken:
                return p
    return None


def gather(ctx, files):
    """Items: {paths, kind, note_path, folder_cat, in_inbox, reason?}."""
    if files:
        paths = [Path(f).resolve() for f in files]
    else:
        paths = []
        if ctx.inbox.is_dir():
            for p in sorted(ctx.inbox.iterdir()):
                if p.name.startswith((".", "_")):
                    continue
                if p.is_file():
                    paths.append(p)
                elif p.is_dir():
                    paths += sorted(q for q in p.iterdir() if q.is_file() and not q.name.startswith((".", "_")))
    items, notes = [], []
    refs = []
    for p in paths:
        if p.suffix.lower() in NOTE_EXT:
            notes.append(p)
        else:
            refs.append(p)
    # numbered image sets: same folder, same prefix, _01 _02 ... (two or more)
    groups, singles = {}, []
    for p in refs:
        m = SET_RX.match(p.stem)
        if p.suffix.lower() in IMAGE_EXT and m:
            groups.setdefault((p.parent, m.group(1).lower()), []).append((int(m.group(2)), p))
        else:
            singles.append([p])
    units = []
    for (folder, _pre), members in groups.items():
        members.sort()
        if len(members) >= 2:
            units.append([p for _, p in members])
        else:
            singles.append([members[0][1]])
    units += singles
    units.sort(key=lambda u: str(u[0]).lower())
    taken = set()
    for u in units:
        p = u[0]
        names = [p.name, p.stem]
        if len(u) > 1:
            m = SET_RX.match(p.stem)
            names = [m.group(1)] + [q.name for q in u] + [q.stem for q in u]
        note = _sidecar(p.parent, names, taken)
        if note:
            taken.add(note)
        in_inbox = _inside(p, ctx.inbox)
        folder_cat = None
        if in_inbox and p.parent.resolve() != ctx.inbox.resolve():
            folder_cat = animlib.category_of(p.parent.name)
        it = {"paths": u, "path": p, "note_path": note, "folder_cat": folder_cat, "in_inbox": in_inbox}
        ext = p.suffix.lower()
        kind = _kind_of(ext)
        if not all(q.is_file() for q in u):
            it.update(kind="skip", reason="not found")
        elif kind == "data":
            it.update(kind="skip", reason="phase 4")
        elif kind is None:
            it.update(kind="skip", reason=f"unsupported type '{ext or '(none)'}'")
        else:
            it["kind"] = kind
        items.append(it)
    for n in notes:
        # (lead) README.md in the inbox and any .md that isn't a sidecar are instructions, not references
        if n not in taken and n.suffix.lower() == ".txt" and n.stem.lower() != "readme":
            items.append({"paths": [n], "path": n, "note_path": None, "folder_cat": None,
                          "in_inbox": _inside(n, ctx.inbox), "kind": "skip",
                          "reason": "note without a reference file"})
    return items


def read_note(path):
    if not path:
        return None
    txt = Path(path).read_text(encoding="utf-8-sig", errors="replace").strip()
    return txt or None


def note_category_title(note):
    """(category or None, title-from-note or None) from the note's first line."""
    if not note:
        return None, None
    first = note.splitlines()[0].strip()
    words = first.split(None, 1)
    if not words:
        return None, None
    cat = animlib.category_of(words[0])
    if not cat:
        return None, None
    rest = words[1] if len(words) > 1 else ""
    rest = plain_title(rest.strip().lstrip(":;,-—–|").strip())
    return cat, (rest or None)


TRIM_LINE = re.compile(r"(?im)^\s*trim\s*[:=]\s*(.+?)\s*$")


def trim_of(note):
    """[start, end] seconds from a `trim: a-b` line in the note, or None. Raises animlib.BadTrim when malformed."""
    if not note:
        return None
    m = TRIM_LINE.search(note)
    return animlib.parse_trim(m.group(1)) if m else None


# (critic r2) "match" or "mine" anywhere used to mean own + match: "match the snap of this punch, clip from a youtube
# video" and "not mine, ripped from another game" were both filed as the user's own work. Now `own` needs an
# explicit, un-negated claim; any named source makes it third-party; a claim plus a source is ambiguous (the skill
# asks); `match` needs own work AND a wish for a faithful copy.
_NEG_OWN = re.compile(r"\b(?:not|isn'?t|aren'?t|wasn'?t|weren'?t|ain'?t|never|none\s+of\s+(?:this|it|these|them)"
                      r"\s+(?:is|are|was))\s+(?:really\s+|actually\s+)?(?:mine\b|my\s+own\b|my\b)"
                      r"|\b(?:didn'?t|did\s+not|never|don'?t|do\s+not)\s+(?:make|made|record|recorded|animate|"
                      r"animated|film|filmed|create|created|shoot|shot|capture|captured|own)\b", re.I)
_OWN_STRONG = re.compile(
    r"\bmy\s+own\b"
    r"|\b(?:i|we)\s+(?:(?:have|'ve|just|myself)\s+)?(?:made|recorded|animated|filmed|shot|created|captured|"
    r"mocapped|keyframed|did)\b"
    r"|\b(?:i|we)'ve\s+(?:made|recorded|animated|filmed|shot|created|captured|mocapped|keyframed)\b"
    r"|\bmy\s+(?:(?:own|new|old|first|latest|original|rough|test|best)\s+)?(?:recording|animation|anim|clip|"
    r"capture|mocap|video|footage|take|work|render|edit)s?\b"
    r"|\b(?:it'?s|it\s+is|this\s+is|that'?s|that\s+is|these\s+are|they'?re|all|is|are)\s+mine\b"
    r"|^\s*(?:\w+\s*[:;,\-—–]\s*)?mine\s*[.!]?\s*$", re.I | re.M)
_MINE = re.compile(r"\bmine\b", re.I)
_LICENSED = re.compile(r"\b(?:mixamo|rokoko|actor\s?core|licen[cs]ed?|bought|purchased|paid\s+for|"
                       r"asset\s+store|marketplace|unreal\s+marketplace|fab\.com)\b", re.I)
_NOT_LICENSED = re.compile(r"\b(?:not|un|isn'?t|wasn'?t)[\s-]*licen[cs]ed\b", re.I)
_THIRD_STRONG = re.compile(
    r"\b(?:youtube|youtu\.?be|yt|tiktok|twitter|instagram|insta|reddit|twitch|vimeo|x\.com|pinterest|discord|"
    r"another\s+game|other\s+game|some(?:one|body)\s+else'?s?|rip(?:ped)?|stolen|found\s+(?:it|this|online)|"
    r"movie|film|trailer|streamer|livestream|vod|"
    r"fortnite|valorant|overwatch|street\s+fighter|tekken|mortal\s+kombat|super\s+smash|elden\s+ring|"
    r"dark\s+souls|sekiro|apex\s+legends|minecraft|gta|for\s+honor|half\s+sword|jujutsu|jjs|battlegrounds|tsb|"
    r"genshin|naruto|dragon\s+ball|one\s+piece|demon\s+slayer|devil\s+may\s+cry|god\s+of\s+war|spider-?man|"
    r"zelda|call\s+of\s+duty|counter[\s-]?strike|csgo|cs2|league\s+of\s+legends|fighting\s+game)\b", re.I)
# a generic "from X" names a source too, unless X is the user (my/our) or a time ("from last week")
_THIRD_FROM = re.compile(r"\bfrom\s+(?!my\b|our\b|me\b|us\b|last\b|yesterday\b|today\b|earlier\b|before\b|"
                         r"this\s+morning\b|the\s+(?:start|end|beginning)\b|frame\b|\d)\w+", re.I)
_WANTS_MATCH = re.compile(r"\b(?:match(?:es|ing)?|faithful(?:ly)?|exact(?:ly)?|1:1|one[\s-]to[\s-]one|as[\s-]is|"
                          r"same\s+(?:timing|feel|speed|scale|size)|copy\s+it|recreate\s+it|keep\s+(?:it|the)\s+"
                          r"(?:same|exact))\b", re.I)


def classify_note(note):
    """(provenance, scale, guess) implied by the user's note. guess: "clear" (an explicit claim or a named source),
    "ambiguous" (conflicting or half signals: the skill asks the user; filed as third-party + absolute meanwhile),
    "no_signal" (nothing about where it came from: third-party + absolute, the safe default)."""
    if not note:
        return "third-party", "absolute", "no_signal"
    text = note
    negated = bool(_NEG_OWN.search(text))
    rest = _NEG_OWN.sub(" ", text)                     # "not mine" must not read as "mine"
    licensed = bool(_LICENSED.search(text)) and not _NOT_LICENSED.search(text)
    own = bool(_OWN_STRONG.search(rest))
    weak_own = bool(_MINE.search(rest)) and not own
    third = bool(_THIRD_STRONG.search(text) or _THIRD_FROM.search(rest))
    if licensed:
        return "licensed", "absolute", ("ambiguous" if own else "clear")
    if negated and not own:
        return "third-party", "absolute", "clear"
    if own and (third or negated):
        return "third-party", "absolute", "ambiguous"
    if own:
        return "own", ("match" if _WANTS_MATCH.search(text) else "absolute"), "clear"
    if third:
        return "third-party", "absolute", "clear"
    if weak_own:
        return "third-party", "absolute", "ambiguous"
    return "third-party", "absolute", "no_signal"


def scale_of(note, provenance=None):
    """`match` only for the user's own work they want copied faithfully; everything else is `absolute`."""
    if provenance is None:
        return classify_note(note)[1]
    if provenance != "own":
        return "absolute"
    return "match" if (note and _WANTS_MATCH.search(note)) else "absolute"


def provenance_of(note):
    return classify_note(note)[0]


def meta_of(note, opts):
    """(provenance, scale, provenance_guess) for a file: the --provenance/--scale flags win over the note."""
    prov, scale, guess = classify_note(note)
    if opts.provenance:
        prov, guess = opts.provenance, "override"
        scale = scale_of(note, prov)
    return prov, (opts.scale or scale), guess


# ---------------------------------------------------------------- templates

def _safe(v):
    return str(v).replace("{{", "{ {").replace("}}", "} }")


def _yaml_scalar(v):
    s = str(v)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./\- ]*", s) and not s.endswith(" "):
        return s
    return json.dumps(s, ensure_ascii=False)


def render(template_text, values):
    """Replace only the {{KEY}} placeholders. Frontmatter values become YAML-safe scalars (a quoted
    "{{KEY}}" is replaced quote and all); in the body a multi-line value under a '>' quote stays quoted."""
    text = template_text
    m = re.match(r"^(﻿?---\r?\n)(.*?)(\r?\n---)", text, re.S)
    head, fm, rest = ("", "", text)
    if m:
        head, fm, rest = m.group(1), m.group(2), text[m.end(2):]
    vals = {k: _safe(v) for k, v in values.items()}

    def fm_sub(match):
        q, key = match.group(1) or "", match.group(2)
        if key not in vals:
            return match.group(0)
        if q:
            return json.dumps(vals[key], ensure_ascii=False)
        return _yaml_scalar(vals[key])

    fm = re.sub(r"([\"']?)\{\{([A-Z_]+)\}\}\1", fm_sub, fm)
    out_lines = []
    for line in rest.split("\n"):
        if "{{" in line:
            quoted = line.lstrip().startswith(">")
            for key, v in vals.items():
                tok = "{{" + key + "}}"
                if tok not in line:
                    continue
                if "\n" in v:
                    if quoted:
                        v = v.replace("\r\n", "\n").replace("\n", "\n> ")
                    elif key not in ("SHEETS", "NUMBERS_SUMMARY"):
                        v = " / ".join(x.strip() for x in v.splitlines() if x.strip())
                line = line.replace(tok, v)
        out_lines.append(line)
    return head + fm + "\n".join(out_lines)


def check_templates(ctx):
    problems = []
    for name in (CARD_TPL, BD_TPL):
        p = ctx.tpl / name
        if not p.is_file():
            problems.append(f"template {name} missing from _meta/templates")
            continue
        t = p.read_text(encoding="utf-8-sig")
        if "{{ID}}" not in t:
            problems.append(f"template {name} has no {{{{ID}}}} placeholder (not the animsmith template)")
    return problems


# ---------------------------------------------------------------- hub and index (line endings kept)

def _read_keep(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    return text, nl


def _write_keep(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def add_hub_line(text, nl, line):
    lines = text.split(nl)
    i = next((k for k, l in enumerate(lines) if HUB_END in l), None)
    if i is None:
        raise RuntimeError(f"hub has no {HUB_END} marker")
    lines.insert(i, line)
    lines = [l for k, l in enumerate(lines) if not (l.strip() == NO_ASSETS)]
    return nl.join(lines)


def add_index_row(text, nl, row):
    lines = text.split(nl)
    i = next((k for k, l in enumerate(lines) if INDEX_END in l), None)
    if i is None:
        raise RuntimeError(f"Asset_Library_Index has no {INDEX_END} marker")
    lines.insert(i, row)
    return nl.join(lines)


def _cell(s):
    """Text for a hub line or an index cell: no wikilink brackets, no heading `#`, no cell-splitting `|`, one line."""
    s = str(s).replace("[[", " ").replace("]]", " ").replace("#", " ").replace("|", "/")
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- summaries

def _item(x):
    """A frame, a range or a tuple as plain text: 7, 7–18, (63: 64–68). Never brackets, so no `[[`."""
    if isinstance(x, (list, tuple)):
        if len(x) == 2 and all(isinstance(v, (int, float)) for v in x):
            return f"{x[0]}–{x[1]}"
        if len(x) == 3 and all(isinstance(v, (int, float)) for v in x):
            return f"({x[0]}: {x[1]}–{x[2]})"
        return "(" + ", ".join(_item(v) for v in x) + ")"
    return str(x)


def _lst(xs, k=12):
    xs = list(xs)
    s = ", ".join(_item(x) for x in xs[:k])
    return (s + f", … (+{len(xs) - k})") if len(xs) > k else (s or "none")


def _sync(s):
    """A peak-sync pair as `32 (+1 f)` / `32 (−2 f)` / `32 (±0 f)`."""
    o = s.get("offset_frames") or 0
    sign = "+" if o > 0 else ("−" if o < 0 else "±")
    return f"{s.get('peak')} ({sign}{abs(o):g} f)"


def _nolinks(text):
    """Measured text must never form a wikilink."""
    return text.replace("[[", "[ [").replace("]]", "] ]")


def numbers_summary(nums, decode=None):
    t60 = nums.get("timing_60") or {}
    cam = nums.get("camera") or {}
    lines = [f"All MEASURED by `anim_analyze v2` (`analysis/numbers.json`); 1-based frames at "
             f"{nums.get('fps_analysis')} fps, then the same at 60 fps after `·60:`. Ranges a–b; hit-stops "
             f"(peak: hold from–to)."]
    lines.append(f"- **Clip:** {nums.get('frames')} frames, {nums.get('duration_s')} s; source fps "
                 f"{nums.get('fps_src')}" + (f"; decode {decode}" if decode else "")
                 + (f"; crop {_item(nums.get('crop'))}" if nums.get("crop") else "")
                 + (f"; trim {nums['trim'][0]:g}–{nums['trim'][1]:g} s of the source" if nums.get("trim") else ""))
    lines.append(f"- **Camera:** moving {'yes' if cam.get('moving') else 'no'} (path range "
                 f"{cam.get('path_range_px')} px); shake candidates {_lst(cam.get('shake_candidates') or [])}")
    lines.append(f"- **Peaks:** {_lst(nums.get('peaks') or [])} ·60: {_lst(t60.get('peaks') or [])}")
    lines.append(f"- **Holds:** {_lst(nums.get('holds') or [])} ·60: {_lst(t60.get('holds') or [])}")
    lines.append(f"- **Slow (wind-ups, settles):** {_lst(nums.get('slow_segments') or [])} ·60: "
                 f"{_lst(t60.get('slow_segments') or [])}")
    lines.append(f"- **Hit-stop candidates (peak: hold from–to):** {_lst(nums.get('hitstop_candidates') or [])} "
                 f"·60: {_lst(t60.get('hitstop_candidates') or [])}")
    lines.append(f"- **Extremes:** {_lst(nums.get('extremes') or [])} · **smears:** {_lst(nums.get('smears') or [])}")
    cyc = nums.get("cycle")
    lines.append(f"- **Cycle:** " + (f"{cyc['period_frames']} frames ({cyc['period_s']} s), confidence "
                                     f"{cyc['confidence']}" if cyc else "none found"))
    reg = nums.get("regions") or {}
    if reg.get("lead_lag"):
        ll = "; ".join(f"{c['cell']} onset f{c['onset_frame']} peak f{c['peak_frame']} "
                       f"(xcorr lag {c['xcorr_lag_vs_dominant']:+d})" for c in reg["lead_lag"][:6])
        lines.append(f"- **Regions (3×3 over the subject box):** first {reg.get('first')}, dominant "
                     f"{reg.get('dominant')}; {ll}")
    lines.append(f"- **Key-pose candidates:** {_lst(nums.get('keypose_candidates') or [], 16)}")
    capt = nums.get("capture") or {}
    if capt:
        lines.append(f"- **Capture:** true fps ≈ {capt.get('true_fps')}, stepping {capt.get('stepping')}, "
                     f"{len(capt.get('duplicate_frames') or [])} duplicate frames, dropped-frame suspects "
                     f"{_lst(capt.get('dropped_frame_suspects') or [])}")
    au = nums.get("audio")
    if au:
        if au.get("onsets"):
            # (critic r2) a (peak, offset) pair printed as a range: "32–1" read as frames 32 to 1
            lines.append(f"- **Audio onsets (ms):** {_lst([o['ms'] for o in au['onsets']])}; peak sync "
                         f"{_lst([_sync(s) for s in au.get('peak_sync') or []])} "
                         f"(peak frame, then the sound's offset in frames: + after the peak, − before)")
        else:
            lines.append(f"- **Audio:** {au.get('note') or 'no onsets'}")
    de = nums.get("decode_errors")
    if de:
        lines.append(f"- **WEAK, decoder errors:** {de.get('events')} error(s), {de.get('lost_frames')} dropped "
                     f"frame(s) near frames {_lst(de.get('suspect_frames') or [])}; affected: "
                     + ("; ".join(f"{k} {_lst(v)}" for k, v in (de.get("affected") or {}).items()) or "none"))
    for n in nums.get("notes") or []:
        if not n.startswith("audio:"):           # the audio line above already says it
            lines.append(f"- _Note:_ {n}")
    return _nolinks("\n".join(lines))


def analyst_frames(nums, frames_dir):
    """Up to 6 frames for the analyst, all from the key-pose candidates: the contact or fastest frame first, then
    the start, the end, slow/hold edges and extremes. Only frames that exist on disk."""
    n = nums.get("frames") or 0
    if not n:
        return []
    detail = nums.get("keypose_detail") or [{"frame": f, "type": ""} for f in nums.get("keypose_candidates") or []]
    cands = [d["frame"] for d in detail]
    en = nums.get("energy") or []
    order = {"contact": 0, "fast": 1, "start": 2, "end": 2, "slow": 3, "hold": 3, "extreme": 4}
    pick = sorted(detail, key=lambda d: (order.get(d.get("type"), 5),
                                         -(en[d["frame"] - 1] if 0 < d["frame"] <= len(en) else 0)))
    out = []
    for d in pick:
        f = d["frame"]
        if f in cands and f not in out and 1 <= f <= n and (Path(frames_dir) / f"f_{f:04d}.jpg").is_file():
            out.append(f)
        if len(out) >= ANALYST_FRAMES:
            break
    return [str(Path(frames_dir) / f"f_{f:04d}.jpg") for f in sorted(out)]


# ---------------------------------------------------------------- roblox key timing

def _rotmat(r):
    import numpy as np
    x, y, z = [float(v) * np.pi / 180 for v in (list(r) + [0, 0, 0])[:3]]
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rx @ Ry @ Rz           # CFrame.fromEulerAnglesXYZ order


def _key_time(k, fps):
    if "t" in k:
        return float(k["t"])
    if "time" in k:
        return float(k["time"])
    return float(k.get("f", k.get("frame", 0))) / fps


def key_numbers(seq, ID, scan):
    import numpy as np
    spec = seq.get("spec") or {}
    fps = float(spec.get("fps") or seq.get("fps_guess") or 30)
    length_s = float(seq.get("length_s") or (float(spec.get("length", 0)) / fps if spec.get("length") else 0))
    tracks = spec.get("tracks") or {}
    times = set()
    parts, peaks = {}, []
    for part, keys in tracks.items():
        if not isinstance(keys, list):
            continue
        ks = sorted((k for k in keys if isinstance(k, dict)), key=lambda k: _key_time(k, fps))
        for k in ks:
            times.add(round(_key_time(k, fps), 4))
        best = None
        for a, b in zip(ks, ks[1:]):
            if "r" not in a or "r" not in b:
                continue
            dt = _key_time(b, fps) - _key_time(a, fps)
            if dt <= 1e-6:
                continue
            Ra, Rb = _rotmat(a["r"]), _rotmat(b["r"])
            c = (np.trace(Ra.T @ Rb) - 1) / 2
            ang = float(np.degrees(np.arccos(np.clip(c, -1, 1))))
            spd = ang / dt
            seg = [int(round(_key_time(a, fps) * fps)) + 1, int(round(_key_time(b, fps) * fps)) + 1]
            if best is None or spd > best[0]:
                best = (spd, seg, ang)
        parts[part] = {"keys": len(ks), "peak_deg_s": round(best[0], 1) if best else None,
                       "peak_between_frames": best[1] if best else None,
                       "peak_angle_deg": round(best[2], 1) if best else None}
        if best:
            peaks.append({"part": part, "deg_s": round(best[0], 1), "frames": best[1]})
    peaks.sort(key=lambda p: -p["deg_s"])
    markers = []
    for mk in (seq.get("markers") or spec.get("markers") or []):
        if not isinstance(mk, dict):
            continue
        t = _key_time(mk, fps)
        markers.append({"name": mk.get("name") or mk.get("marker") or "?", "t": round(t, 4),
                        "f": int(round(t * fps)) + 1, "f60": int(round(t * 60)) + 1})
    ts = sorted(times)
    notes = ["keyframe data: no pixels, so camera, energy, regions and sheets don't apply",
             "angular speed = rotation angle between consecutive keys (XYZ euler, degrees) / time; easing ignored"]
    if scan.get("suspicious"):
        notes.append("script scan: suspicious items in the file: " + "; ".join(fmt_suspicious(scan["suspicious"])))
    return {"id": ID, "analyzer": "anim_intake key timing", "source": "data", "name": seq.get("name"),
            "path_in_file": seq.get("path_in_file"), "label": "MEASURED from the keyframe data (exact)",
            "frame_base": 1, "spec_frame_offset": -1,     # (critic r3) spec f = these f - 1 (the spec is 0-based)
            "fps_src": seq.get("fps_guess") or fps, "fps_analysis": fps, "fps_spec": fps,
            "frames": int(round(length_s * fps)) + 1,           # frames 1..N include the key at length_s
            "duration_s": round(length_s, 4), "crop": None, "loop": seq.get("loop"),
            "priority": seq.get("priority"), "rig": spec.get("rig"),
            "keys": {"count": len(ts), "times_s": ts, "frames": [int(round(t * fps)) + 1 for t in ts]},
            "markers": markers, "parts": parts, "speed_peaks": peaks[:8],
            "timing_60": {"key_frames": [int(round(t * 60)) + 1 for t in ts],
                          "markers": [{"name": m["name"], "f60": m["f60"]} for m in markers],
                          "speed_peaks": [{"part": p["part"], "frames": [int(round((f - 1) * 60 / fps)) + 1
                                                                          for f in p["frames"]]}
                                          for p in peaks[:8]],
                          "frames": int(round(length_s * 60)) + 1},
            "scan": scan, "notes": notes}


def fmt_suspicious(items):
    """anim_catalog reports {path, class, name, flags}; older or other shapes print as they are."""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(f"{it.get('path') or it.get('name')} ({it.get('class', '?')}): "
                       f"{', '.join(it.get('flags') or []) or 'flagged'}")
        else:
            out.append(str(it))
    return out


def keys_summary(nums):
    sc = nums.get("scan") or {}
    lines = ["All MEASURED from the keyframe data (exact; decoded offline, never opened in Studio)."]
    if nums.get("quarantine"):
        lines.append(f"- **QUARANTINED:** the script scan flagged this file, so its source is stored as "
                     f"`source/{nums['quarantine']}` (not a loadable extension). Never rename it, open it or insert "
                     f"it in Studio; the keys here were decoded offline.")
    if sc.get("suspicious"):
        lines.append(f"- **WARNING, script scan:** {sc.get('scripts', 0)} script(s) in the file (never run or "
                     f"copied); suspicious: {'; '.join(fmt_suspicious(sc['suspicious'])[:8])}")
    else:
        lines.append(f"- **Script scan:** {sc.get('scripts', 0)} script(s) in the file (never run or copied); "
                     f"nothing suspicious")
    lines.append(f"- **Sequence:** `{nums.get('name')}` ({nums.get('path_in_file')}), {nums.get('duration_s')} s "
                 f"(keys at ~{nums.get('fps_src')} fps; spec frames at {nums.get('fps_spec')} fps), loop {nums.get('loop')}, priority {nums.get('priority')}, rig "
                 f"{nums.get('rig')}")
    k = nums.get("keys") or {}
    lines.append(f"- **Key times:** {k.get('count')} distinct; frames {_lst(k.get('frames') or [], 16)}")
    lines.append(f"- **Markers:** {_lst([(m['name'], m['f']) for m in nums.get('markers') or []])}")
    lines.append(f"- **Angular speed peaks (deg/s, between frames):** "
                 f"{_lst([(p['part'], p['deg_s'], p['frames']) for p in nums.get('speed_peaks') or []], 6)}")
    return _nolinks("\n".join(lines))


# ---------------------------------------------------------------- filing one reference

def _post_success_hook(ctx, recs):
    """Test seam: a failure here must roll the whole file back."""
    return None


class Undo:
    """Everything this run made for one input file, so a failure removes exactly that."""

    def __init__(self, ctx):
        self.ctx, self.files, self.dirs, self.texts, self.ids = ctx, [], [], {}, []

    def mkdirs(self, path):
        """mkdir -p, remembering every folder this made (outermost first) so a rollback removes them too."""
        path = Path(path)
        made, p = [], path
        while not p.exists():
            made.append(p)
            p = p.parent
        path.mkdir(parents=True, exist_ok=True)
        self.dirs += list(reversed(made))
        return path

    def save_text(self, path):
        if path not in self.texts:
            self.texts[path] = Path(path).read_bytes()

    def rollback(self):
        for p, old in self.texts.items():
            try:
                Path(p).write_bytes(old)
            except Exception:
                pass
        for p in reversed(self.files):
            try:
                Path(p).unlink()
            except Exception:
                pass
        for d in reversed(self.dirs):
            shutil.rmtree(d, ignore_errors=True)


def claim(ctx, cat, undo):
    undo.mkdirs(ctx.media)
    reg = ctx.lib / animlib.IDS_FILE
    if reg.is_file():
        undo.save_text(reg)                 # restored byte for byte on rollback
    elif reg not in undo.files:
        undo.mkdirs(reg.parent)
        undo.files.append(reg)
    for _ in range(200):
        ID = animlib.next_id(ctx.vault, cat)
        try:
            mdir = animlib.claim_id(ctx.vault, ID)
        except FileExistsError:
            continue
        undo.dirs.append(mdir)
        return ID, mdir
    raise RuntimeError(f"no free {CATEGORIES[cat]['prefix']} id")


def write_new(path, text, undo):
    undo.mkdirs(Path(path).parent)
    with open(path, "x", encoding="utf-8", newline="\n") as fh:   # "x": never overwrite a note
        undo.files.append(path)
        fh.write(text)


def file_notes(ctx, rec, undo):
    """Card, Breakdown, spec dir, hub line and index row for one record."""
    ID, cat = rec["id"], rec["category"]
    meta = CATEGORIES[cat]
    sheets = rec.get("sheet_names") or []
    sheet_md = ("\n".join(f"![[{s}]]" for s in sheets) if sheets
                else "_No sheets: " + ("keyframe data, see the spec." if rec["kind"] == "roblox" else "none made.")
                + "_")
    values = {"ID": ID, "TITLE": plain_title(rec["title"], None), "CATEGORY": cat, "CAT_TAG": meta["tag"], "HUB": meta["hub"],
              "DATE": rec["date"], "SOURCE_FILE": rec["source_name"], "KIND": rec["kind"], "FPS": rec["fps"],
              "DURATION": rec["duration"], "RES": rec["res"], "FRAMES": rec["frames_n"], "RIG": rec["rig"],
              "SCALE": rec["scale"], "USER_NOTE": note_for_card(rec["note"]) or "none", "MEDIA_DIR": f"_media/anim/{ID}",
              "SHEETS": sheet_md, "NUMBERS_SUMMARY": rec["summary"],
              "SPEC_DIR": f"11_ASSET_LIBRARY/Animation/_specs/{ID}/", "PROVENANCE": rec["provenance"]}
    texts = []
    for tpl in (CARD_TPL, BD_TPL):
        t = render((ctx.tpl / tpl).read_text(encoding="utf-8-sig"), values)
        left = sorted(set(re.findall(r"\{\{[^}]*\}\}", t)))
        if left:
            raise RuntimeError(f"{tpl}: placeholders left after filling: {left}")
        texts.append(t)
    card = ctx.guard(ctx.card_path(cat, ID))
    bd = ctx.guard(ctx.bddir / f"Breakdown_{ID}.md")
    write_new(card, texts[0], undo)
    write_new(bd, texts[1], undo)
    spec_dir = ctx.guard(ctx.specs / ID)
    if not spec_dir.is_dir():
        undo.mkdirs(spec_dir)
    hub = ctx.hub(cat)
    if not hub.is_file():
        raise RuntimeError(f"hub note {hub.name} missing")
    undo.save_text(hub)
    text, nl = _read_keep(hub)
    _write_keep(ctx.guard(hub), add_hub_line(text, nl, f"- [[{ID}]] — {_cell(rec['title'])} · {rec['kind']} · "
                                                        f"breakdown not-started"))
    undo.save_text(ctx.index)
    text, nl = _read_keep(ctx.index)
    row = (f"| [[{ID}]] | {cat} | {_cell(rec['title'])} | — | — | {_cell(rec['length'])} | not-started | none |")
    _write_keep(ctx.guard(ctx.index), add_index_row(text, nl, row))
    rec.update(card=str(card), breakdown=str(bd), spec_dir=str(spec_dir))


def _base_rec(it, cat, note, title, opts):
    prov, scale, guess = meta_of(note, opts)
    return {"category": cat, "kind": it["kind"], "title": title, "note": note,
            "note_name": it["note_path"].name if it["note_path"] else None,
            "scale": scale, "provenance": prov, "provenance_guess": guess,
            "date": _today(),
            "source_name": it["path"].name if len(it["paths"]) == 1 else
            ", ".join(p.name for p in it["paths"]),
            "rig": {"r6": "R6", "r15": "R15"}.get((opts.rig or "unknown").lower(), "unknown")}


def copy_sidecar(ctx, it, mdir):
    """(critic r2) The sidecar note goes into source/ next to the original (the inbox copy is deleted afterwards,
    with the original). Returns the stored path or None."""
    np_ = it.get("note_path")
    if not np_ or not Path(np_).is_file():
        return None
    dst = ctx.guard(mdir / "source" / free_name(mdir / "source", Path(np_).name))
    shutil.copy2(np_, dst)
    return dst


def process_media(ctx, it, cat, note, title, opts, undo):
    """video, gif or images -> one record."""
    rec = _base_rec(it, cat, note, title, opts)
    ID, mdir = claim(ctx, cat, undo)
    rec["id"] = ID
    for sub in ("source", "frames", "sheets", "analysis"):
        (mdir / sub).mkdir(exist_ok=False)
    for p in it["paths"]:
        shutil.copy2(p, ctx.guard(mdir / "source" / free_name(mdir / "source", p.name)))
    copy_sidecar(ctx, it, mdir)
    if it["kind"] in ("video", "gif"):
        src = it["path"]
        trim = opts.trim or trim_of(note)
        ex = animlib.extract_frames(src, mdir / "frames", gpu=opts.gpu_on, crop=opts.crop, trim=trim)
        nums = anim_analyze.analyze(
            mdir / "frames", ex["fps"], mdir / "analysis", id=ID, sheets_dir=mdir / "sheets",
            fps_src=ex["fps_src"], source=str(src), notes=ex["notes"], trim=ex["trim"],
            decode_errors=ex.get("decode_errors"))
        nums["decode"] = ex["decode"]
        nums["crop_source"] = opts.crop
        anim_analyze.write_numbers(mdir / "analysis", nums)
        rec["trim"] = ex["trim"]
        pr = ex["probe"]
        dur = (ex["trim"][1] - ex["trim"][0]) if ex["trim"] else pr["duration"]
        rec.update(fps=f"{pr['fps']:g}", duration=f"{dur:g}", res=f"{pr['width']}x{pr['height']}",
                   frames_n=str(ex["frames"]), summary=numbers_summary(nums, ex["decode"]),
                   length=f"{dur:g}s @ {pr['fps']:g}", decode=ex["decode"],
                   analyst_frames=analyst_frames(nums, mdir / "frames"))
        sheet_paths = [nums["sheets"][k] for k in ("contact", "keyposes", "strips", "onion", "motion")]
    else:
        ims = []
        for i, p in enumerate(it["paths"], 1):
            im = animlib.load_rgb(p)
            if opts.crop:
                x, y, w, h = opts.crop
                im = im.crop((x, y, x + w, y + h))
            im = animlib.fit(im, 960, 960)
            out = ctx.guard(mdir / "frames" / f"f_{i:04d}.jpg")
            animlib.save_image(im, out)
            ims.append((out, f"f{i}  {it['paths'][i - 1].name}"))
        from PIL import Image
        with Image.open(it["path"]) as im0:
            W, H = im0.size
        sheet = animlib.sheet(ims, mdir / "sheets" / f"{ID}_contact.jpg", cols=min(4, len(ims)),
                              title=f"{ID}  {len(ims)} image(s)")
        nums = {"id": ID, "analyzer": "anim_intake images", "kind": "images", "frames": len(ims),
                "fps_src": None, "fps_analysis": None, "duration_s": None, "crop": opts.crop,
                "frame_size": [W, H], "label": "still images: contact sheet only",
                "notes": ["still images: no motion, timing or camera can be measured"]
                + (["trim: ignored for still images"] if (opts.trim or trim_of(note)) else [])}
        anim_analyze.write_numbers(mdir / "analysis", nums)
        rec.update(fps="n/a", duration="n/a", res=f"{W}x{H}", frames_n=str(len(ims)),
                   summary=f"- **Images:** {len(ims)} still(s), first {W}x{H}; contact sheet only "
                           f"(no motion measured).",
                   length=f"{len(ims)} image" + ("s" if len(ims) != 1 else ""), decode=None,
                   analyst_frames=[str(p) for p, _ in ims[:ANALYST_FRAMES]])
        sheet_paths = [str(sheet)]
    rec.update(media_dir=str(mdir), numbers=str(mdir / "analysis" / "numbers.json"),
               numbers_brief=str(mdir / "analysis" / "numbers_brief.json"), sheets=sheet_paths,
               sheet_names=[Path(s).name for s in sheet_paths])
    file_notes(ctx, rec, undo)
    return [rec]


def load_catalog():
    try:
        return importlib.import_module("anim_catalog")
    except ImportError:
        return None


def process_roblox(ctx, it, cat, note, title, opts, undo, data):
    recs = []
    scan = data.get("scan") or {}
    seqs = data.get("sequences") or []
    first = None
    for k, seq in enumerate(seqs):
        name = seq.get("name") or f"sequence {k + 1}"
        t = (f"{title} — {plain_title(name)}" if (title and len(seqs) > 1) else (title or _clean_title(name)))
        rec = _base_rec(it, cat, note, t, opts)
        ID, mdir = claim(ctx, cat, undo)
        rec["id"] = ID
        for sub in ("source", "frames", "sheets", "analysis"):
            (mdir / sub).mkdir(exist_ok=False)
        quarantine = (it["path"].name + ".quarantine") if scan.get("suspicious") else None
        stored = quarantine or it["path"].name
        if first is None:
            # a flagged pack is stored under a name Studio won't load, so it can't be opened or inserted by accident
            shutil.copy2(it["path"], ctx.guard(mdir / "source" / stored))
            copy_sidecar(ctx, it, mdir)
            first = ID
        else:
            (mdir / "source" / "SOURCE.txt").write_text(
                f"The source file {it['path'].name} is kept once, in _media/anim/{first}/source/{stored}"
                + (" (QUARANTINED: its script scan flagged it; never rename or open it in Studio)" if quarantine
                   else "") + ".\n", encoding="utf-8")
        spec = dict(seq.get("spec") or {})
        spec["id"] = ID
        spec["source"] = "data"
        spec["provenance"] = rec["provenance"]
        spec.setdefault("category", cat)
        spec_dir = ctx.guard(ctx.specs / ID)
        if spec_dir.exists():
            raise RuntimeError(f"spec folder {spec_dir.name} already exists")
        undo.mkdirs(spec_dir)
        spec_path = spec_dir / f"{ID}_v001.json"
        animlib.write_json(spec_path, spec)
        nums = key_numbers(seq, ID, scan)
        if quarantine:
            nums["quarantine"] = quarantine
            nums["notes"].append(f"quarantined: source stored as source/{quarantine} (script scan flagged it)")
        anim_analyze.write_numbers(mdir / "analysis", nums)
        rig = spec.get("rig") if spec.get("rig") in ("R6", "R15") else rec["rig"]
        rec.update(rig=rig, fps=f"{nums['fps_src']:g}", duration=f"{nums['duration_s']:g}",
                   res="n/a (keyframe data)", frames_n=str(nums["frames"]), summary=keys_summary(nums),
                   length=f"{nums['duration_s']:g}s @ {nums['fps_src']:g} (keys)", decode=None,
                   analyst_frames=[], media_dir=str(mdir), numbers=str(mdir / "analysis" / "numbers.json"),
                   numbers_brief=str(mdir / "analysis" / "numbers_brief.json"),
                   sheets=[], sheet_names=[], spec=str(spec_path), scan=scan, quarantine=quarantine,
                   source_name=(f"{stored} (QUARANTINED)" if quarantine else it["path"].name)
                   + (f" :: {seq.get('path_in_file')}" if seq.get("path_in_file") else ""))
        file_notes(ctx, rec, undo)
        recs.append(rec)
    return recs


def delete_inbox(ctx, it):
    """Remove filed inbox originals and their sidecar. Returns the names that couldn't be deleted."""
    kept = []
    for p in list(it["paths"]) + ([it["note_path"]] if it["note_path"] else []):
        if p and p.exists() and _inside(p, ctx.inbox):
            try:
                p.unlink()
            except OSError as e:
                kept.append(f"{p.name} ({type(e).__name__})")
    return kept


# ---------------------------------------------------------------- refile (category correction)

def _id_rx(ID):
    return re.compile(re.escape(ID) + r"(?!\d)")


def find_card(ctx, ID):
    for cat, meta in CATEGORIES.items():
        p = ctx.lib / meta["folder"] / f"{ID}.md"
        if p.is_file():
            return cat, p
    return None, None


def _fm_value(text, key):
    m = re.search(r"(?m)^" + re.escape(key) + r":[ \t]*(.*)$", text.split("\n---", 1)[0])
    if not m:
        return None
    v = re.split(r"\s+#", m.group(1), maxsplit=1)[0].strip()
    if v.startswith('"'):
        try:
            return json.loads(v)
        except ValueError:
            return v.strip('"')
    return v


def _retext(text, old_id, new_id, old_cat, new_cat):
    o, n = CATEGORIES[old_cat], CATEGORIES[new_cat]
    text = _id_rx(old_id).sub(new_id, text)
    text = text.replace(f"[[{o['hub']}]]", f"[[{n['hub']}]]")
    text = re.sub(r"(?m)^(\s*-\s*)" + re.escape(o["tag"]) + r"\s*$", lambda m: m.group(1) + n["tag"], text)
    text = re.sub(r"(?m)^category:([ \t]*)" + re.escape(old_cat) + r"\b",
                  lambda m: f"category:{m.group(1)}{new_cat}", text)
    return text


def add_alias(text, alias):
    """Add alias to the frontmatter `aliases:` (flow list or block list); adds the key when missing."""
    m = re.match(r"^(\ufeff?---\r?\n)(.*?)(\r?\n---)", text, re.S)
    if not m:
        return text
    fm = m.group(2)
    nl = "\r\n" if "\r\n" in fm else "\n"
    fl = re.search(r"(?m)^aliases:[ \t]*\[(.*?)\][ \t]*$", fm)
    if fl:
        items = [x.strip().strip('"').strip("'") for x in fl.group(1).split(",") if x.strip()]
        if alias in items:
            return text
        items.append(alias)
        fm = fm[:fl.start()] + "aliases: [" + ", ".join(items) + "]" + fm[fl.end():]
    else:
        bl = re.search(r"(?m)^aliases:[ \t]*$", fm)
        if bl:
            if re.search(r"(?m)^\s*-\s*" + re.escape(alias) + r"\s*$", fm):
                return text
            fm = fm[:bl.end()] + nl + "  - " + alias + fm[bl.end():]
        else:
            fm = "aliases: [" + alias + "]" + nl + fm
    return m.group(1) + fm + text[m.end(2):]


LINK_SKIP = {".obsidian", ".git", ".trash", "_media", "__pycache__", "_inbox"}


def rewrite_links(ctx, old_id, new_id, undo, skip=()):
    """[[old ID]], [[old ID|..]], [[old ID#..]] and [[Breakdown_old ID...]] -> the new ID in every other vault note.
    Returns the notes changed (each saved in undo first)."""
    rx = re.compile(r"\[\[(Breakdown_)?" + re.escape(old_id) + r"(?!\d)(?=[\]|#^])")
    skip = {Path(x).resolve() for x in skip}
    changed = []
    for dirpath, dirnames, filenames in os.walk(ctx.vault):
        dirnames[:] = [d for d in dirnames if d not in LINK_SKIP]
        for name in filenames:
            if not name.lower().endswith(".md"):
                continue
            path = Path(dirpath) / name
            if path.resolve() in skip:
                continue
            try:
                text, nl = _read_keep(path)
            except (OSError, UnicodeDecodeError):
                continue
            if old_id not in text:
                continue
            new = rx.sub(lambda m: "[[" + (m.group(1) or "") + new_id, text)
            if new != text:
                if not _inside(path, ctx.vault):
                    continue
                undo.save_text(path)
                _write_keep(path, new)
                changed.append(str(path))
    return changed


def _copy_renamed(src_dir, dst_dir, rx, new_id, old_id, old_cat, new_cat):
    for src in sorted(src_dir.rglob("*")):
        dst = dst_dir / rx.sub(new_id, str(src.relative_to(src_dir)))
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() == ".json":
            data = animlib.read_json(src)
            if isinstance(data, dict):
                if data.get("id") == old_id:
                    data["id"] = new_id
                if data.get("category") == old_cat:
                    data["category"] = new_cat
                text = json.dumps(data, indent=1, ensure_ascii=False)
            else:
                text = src.read_text(encoding="utf-8-sig")
            dst.write_text(rx.sub(new_id, text), encoding="utf-8")
        elif src.suffix.lower() in (".txt", ".md"):
            dst.write_text(rx.sub(new_id, src.read_text(encoding="utf-8-sig")), encoding="utf-8")
        else:
            shutil.copy2(src, dst)


def refile(ctx, old_id, new_cat):
    """Move a filed reference to another category: a new ID in the new prefix; card, Breakdown, media folder and
    specs folder renamed with the ID text replaced inside them; hub line moved; index row updated. The old ID
    stays unused (the registry keeps it). Copies first and deletes the old files only once all is in place."""
    old_cat, old_card = find_card(ctx, old_id)
    if not old_cat:
        raise RuntimeError(f"no card {old_id}.md in any Animation/<Cat>/ folder")
    if old_cat == new_cat:
        raise RuntimeError(f"{old_id} is already in {new_cat}")
    undo = Undo(ctx)
    old_bd = ctx.bddir / f"Breakdown_{old_id}.md"
    old_media = ctx.media / old_id
    old_spec = ctx.specs / old_id
    rx = _id_rx(old_id)
    try:
        new_id, mdir = claim(ctx, new_cat, undo)
        if old_media.is_dir():
            _copy_renamed(old_media, ctx.guard(mdir), rx, new_id, old_id, old_cat, new_cat)
        new_spec = ctx.guard(ctx.specs / new_id)
        if new_spec.exists():
            raise RuntimeError(f"spec folder {new_spec.name} already exists")
        undo.mkdirs(new_spec)
        if old_spec.is_dir():
            _copy_renamed(old_spec, new_spec, rx, new_id, old_id, old_cat, new_cat)
        card_text = add_alias(_retext(old_card.read_text(encoding="utf-8-sig"), old_id, new_id, old_cat, new_cat),
                              old_id)
        new_card = ctx.guard(ctx.card_path(new_cat, new_id))
        write_new(new_card, card_text, undo)
        new_bd = None
        if old_bd.is_file():
            new_bd = ctx.guard(ctx.bddir / f"Breakdown_{new_id}.md")
            write_new(new_bd, add_alias(_retext(old_bd.read_text(encoding="utf-8-sig"), old_id, new_id, old_cat,
                                                new_cat), f"Breakdown_{old_id}"), undo)
        h1 = re.search(r"(?m)^# .*? — (.+)$", card_text)
        title = h1.group(1).strip() if h1 else new_id
        kind = _fm_value(card_text, "kind") or "?"
        moved = None
        oh = ctx.hub(old_cat)
        if oh.is_file():
            undo.save_text(oh)
            text, nl = _read_keep(oh)
            keep = []
            for line in text.split(nl):
                if moved is None and f"[[{old_id}]]" in line:
                    moved = rx.sub(new_id, line)
                else:
                    keep.append(line)
            _write_keep(ctx.guard(oh), nl.join(keep))
        nh = ctx.hub(new_cat)
        if not nh.is_file():
            raise RuntimeError(f"hub note {nh.name} missing")
        undo.save_text(nh)
        text, nl = _read_keep(nh)
        _write_keep(ctx.guard(nh), add_hub_line(text, nl, moved or f"- [[{new_id}]] — {_cell(title)} · {kind} · "
                                                                     f"breakdown not-started"))
        undo.save_text(ctx.index)
        text, nl = _read_keep(ctx.index)
        lines = text.split(nl)
        hit = False
        for k, line in enumerate(lines):
            if f"[[{old_id}]]" in line:
                cells = line.split("|")
                if len(cells) > 3 and cells[2].strip() == old_cat:
                    cells[2] = f" {new_cat} "
                lines[k] = rx.sub(new_id, "|".join(cells))
                hit = True
                break
        text = nl.join(lines)
        if not hit:
            text = add_index_row(text, nl, f"| [[{new_id}]] | {new_cat} | {_cell(title)} | — | — | — | "
                                           f"not-started | none |")
        _write_keep(ctx.guard(ctx.index), text)
        linked = rewrite_links(ctx, old_id, new_id, undo, skip=[old_card, old_bd, new_card] + ([new_bd] if new_bd
                                                                                              else []))
        _post_success_hook(ctx, [{"id": new_id}])
    except BaseException:
        undo.rollback()
        raise
    for p in (old_card, old_bd):
        if p.is_file():
            p.unlink()
    for d in (old_media, old_spec):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    nums = mdir / "analysis" / "numbers.json"
    sheets = sorted(str(p) for p in (mdir / "sheets").glob("*")) if (mdir / "sheets").is_dir() else []
    note = _fm_value(card_text, "user_note")
    spec = sorted(new_spec.glob("*.json"))
    return {"id": new_id, "refiled_from": old_id, "kind": kind, "category": new_cat, "title": title,
            "file": str(old_card), "card": str(new_card), "breakdown": str(new_bd) if new_bd else None,
            "media_dir": str(mdir), "numbers": str(nums) if nums.is_file() else None, "sheets": sheets,
            "frames": [], "user_note": None if note in (None, "none") else note,
            "scale": _fm_value(card_text, "scale"), "provenance": _fm_value(card_text, "provenance"),
            "rig": _fm_value(card_text, "rig_source"), "spec_dir": str(new_spec),
            "spec": str(spec[0]) if spec else None, "inbox_kept": False, "reason": None,
            "numbers_brief": str(mdir / "analysis" / "numbers_brief.json")
            if (mdir / "analysis" / "numbers_brief.json").is_file() else None,
            "links_rewritten": linked,
            "touched": [str(new_card)] + ([str(new_bd)] if new_bd else []) + [str(ctx.hub(old_cat)),
                                                                             str(ctx.hub(new_cat)), str(ctx.index)]
            + linked}


# ---------------------------------------------------------------- pack and set-meta (filed IDs)

def pack_block(ctx, ID):
    """The per-reference block for a filed ID (the analyst's inputs), read back from the vault."""
    cat, card = find_card(ctx, ID)
    if not cat:
        raise RuntimeError(f"no card {ID}.md in any Animation/<Cat>/ folder")
    text = card.read_text(encoding="utf-8-sig")
    mdir = ctx.media / ID
    nums_p = mdir / "analysis" / "numbers.json"
    brief_p = mdir / "analysis" / "numbers_brief.json"
    nums = animlib.read_json(nums_p, {}) if nums_p.is_file() else {}
    if nums and not brief_p.is_file():
        anim_analyze.write_numbers(mdir / "analysis", nums)     # older references: make the brief now
    kind = _fm_value(text, "kind") or nums.get("kind") or "?"
    frames_dir = mdir / "frames"
    if kind in ("video", "gif"):
        frames = analyst_frames(nums, frames_dir)
    elif kind == "images":
        frames = [str(f) for f in sorted(frames_dir.glob("f_*.jpg"))[:ANALYST_FRAMES]]
    else:
        frames = []
    sheets = sorted(str(x) for x in (mdir / "sheets").glob("*")) if (mdir / "sheets").is_dir() else []
    specs = sorted((ctx.specs / ID).glob("*.json")) if (ctx.specs / ID).is_dir() else []
    bd = ctx.bddir / f"Breakdown_{ID}.md"
    note = _fm_value(text, "user_note")
    h1 = re.search(r"(?m)^# .*? — (.+)$", text)
    return {"id": ID, "kind": kind, "category": cat, "title": h1.group(1).strip() if h1 else ID,
            "card": str(card), "breakdown": str(bd) if bd.is_file() else None,
            "media_dir": str(mdir) if mdir.is_dir() else None,
            "numbers": str(nums_p) if nums_p.is_file() else None,
            "numbers_brief": str(brief_p) if brief_p.is_file() else None,
            "sheets": sheets, "frames": frames, "spec": str(specs[-1]) if specs else None,
            "spec_dir": str(ctx.specs / ID), "user_note": None if note in (None, "none") else note,
            "scale": _fm_value(text, "scale"), "provenance": _fm_value(text, "provenance"),
            "rig": _fm_value(text, "rig_source"), "trim": nums.get("trim"),
            "breakdown_status": _fm_value(text, "breakdown_status"), "inbox_kept": False, "reason": None}


def _set_fm(text, key, value):
    """Replace a frontmatter key's value, keeping a trailing `# comment`."""
    m = re.match(r"^(\ufeff?---\r?\n)(.*?)(\r?\n---)", text, re.S)
    if not m:
        return text
    fm = m.group(2)
    rx = re.compile(r"(?m)^(" + re.escape(key) + r":[ \t]*)([^#\r\n]*?)([ \t]+#[^\r\n]*)?$")
    if rx.search(fm):
        fm = rx.sub(lambda mm: mm.group(1) + value + (mm.group(3) or ""), fm, count=1)
    else:
        nl = "\r\n" if "\r\n" in fm else "\n"
        fm = fm + nl + f"{key}: {value}"
    return m.group(1) + fm + text[m.end(2):]


def set_meta(ctx, ID, provenance=None, scale=None):
    """Rewrite a filed card's provenance/scale (frontmatter and the `Provenance:` / `Scale:` body lines), the
    Breakdown's `Scale:` mention and the specs' provenance. Returns the touched paths."""
    cat, card = find_card(ctx, ID)
    if not cat:
        raise RuntimeError(f"no card {ID}.md in any Animation/<Cat>/ folder")
    undo = Undo(ctx)
    touched = []
    try:
        text, nl = _read_keep(card)
        new = text
        if provenance:
            new = _set_fm(new, "provenance", provenance)
            new = re.sub(r"(Provenance: `)[^`\r\n]*(`)", lambda m: m.group(1) + provenance + m.group(2), new)
        if scale:
            new = _set_fm(new, "scale", scale)
            new = re.sub(r"(Scale: `)[^`\r\n]*(`)", lambda m: m.group(1) + scale + m.group(2), new)
        if new != text:
            undo.save_text(card)
            _write_keep(ctx.guard(card), new)
            touched.append(str(card))
        bd = ctx.bddir / f"Breakdown_{ID}.md"
        if bd.is_file() and scale:
            text, nl = _read_keep(bd)
            new = re.sub(r"(Scale: `)[^`\r\n]*(`)", lambda m: m.group(1) + scale + m.group(2), text)
            if new != text:
                undo.save_text(bd)
                _write_keep(ctx.guard(bd), new)
                touched.append(str(bd))
        if provenance and (ctx.specs / ID).is_dir():
            for sp in sorted((ctx.specs / ID).glob("*.json")):
                data = animlib.read_json(sp)
                if isinstance(data, dict) and "provenance" in data and data["provenance"] != provenance:
                    undo.save_text(sp)
                    data["provenance"] = provenance
                    animlib.write_json(ctx.guard(sp), data)
                    touched.append(str(sp))
    except BaseException:
        undo.rollback()
        raise
    return touched


# ---------------------------------------------------------------- vault tools

_VALIDATE_COUNTS = (("problems", r"Notes with problems: (\d+)"),
                    ("missing", r"Registered but missing files \((\d+)\)"),
                    ("unregistered", r"Files not in registry \((\d+)\)"),
                    ("orphans", r"Orphans \(0 inbound\) \((\d+)\)"))


def problem_blocks(text):
    """validate_vault.py output -> {relative note path: [problem lines]} (blocks of '- <path>' + indented lines)."""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^- (\S.*\.md)\s*$", line)
        if m:
            cur = m.group(1).replace("\\", "/").strip()
            out.setdefault(cur, [])
        elif cur and line.startswith((" ", "\t")) and line.strip():
            out[cur].append(line.strip())
        else:
            cur = None
    return out


def _run_validate(ctx):
    p = ctx.vault / "_meta" / "tools" / "validate_vault.py"
    if not p.is_file():
        return None
    r = subprocess.run([sys.executable, str(p), "--folder", "11_ASSET_LIBRARY"], cwd=str(ctx.vault),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r, (r.stdout + r.stderr).strip()


def validate_baseline(ctx):
    """(critic r2) The validator's problems in notes that exist BEFORE this run writes anything ({relative path:
    [problem lines]}), so problems already in shared notes (hubs, Asset_Library_Index) aren't blamed on this run.
    None when the vault has no validator. Notes that don't exist yet have no baseline (all their problems are new)."""
    got = _run_validate(ctx)
    if got is None:
        return None
    return {k: v for k, v in problem_blocks(got[1]).items() if (ctx.vault / k).is_file()}


_LIST_PROBLEM = re.compile(r"^(.*?):\s*\[(.*)\]\s*$")


def _problem_key(line):
    """A problem line made comparable across runs: the numbers in it don't matter ("only 3 distinct links" and
    "only 4 distinct links" are the same old problem)."""
    return re.sub(r"\d+", "#", line.strip())


def new_problems(lines, before):
    """The problem lines that weren't there before. A list problem ("UNREGISTERED links: ['A', 'B']") is new only
    for the items it gained, and is reported with just those."""
    before = before or []
    old_keys = {_problem_key(b) for b in before}
    old_items = {}
    for b in before:
        m = _LIST_PROBLEM.match(b)
        if m:
            old_items.setdefault(m.group(1).strip(), set()).update(
                x.strip() for x in m.group(2).split(",") if x.strip())
    out = []
    for line in lines:
        m = _LIST_PROBLEM.match(line)
        if m and m.group(1).strip() in old_items:
            items = [x.strip() for x in m.group(2).split(",") if x.strip()]
            gained = [x for x in items if x not in old_items[m.group(1).strip()]]
            if gained:
                out.append(f"{m.group(1).strip()}: [{', '.join(gained)}]")
        elif _problem_key(line) not in old_keys:
            out.append(line)
    return out


def run_tools(ctx, touched=(), baseline=None):
    """build_mocs.py, then validate_vault.py --folder 11_ASSET_LIBRARY. `ok` looks only at problems this run made in
    the notes it wrote (`touched`): problems already in the vault, also ones already in a shared note this run edited
    (`baseline`, from validate_baseline before writing), are counted under `elsewhere` and never fail a run."""
    out = {}
    mine = set()
    for t in touched or ():
        try:
            mine.add(str(Path(t).resolve().relative_to(ctx.vault)).replace("\\", "/"))
        except ValueError:
            pass
    baseline = {k.replace("\\", "/"): v for k, v in (baseline or {}).items()}
    for key, script, args in (("build_mocs", "build_mocs.py", []),
                              ("validate", "validate_vault.py", ["--folder", "11_ASSET_LIBRARY"])):
        p = ctx.vault / "_meta" / "tools" / script
        if not p.is_file():
            out[key] = {"ran": False, "exit": None, "tail": f"skipped: {script} not found in this vault"}
            if key == "validate":
                out[key].update(ok=None, problems=None)
            continue
        r = subprocess.run([sys.executable, str(p), *args], cwd=str(ctx.vault), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        text = (r.stdout + r.stderr).strip()
        res = {"ran": True, "exit": r.returncode, "tail": "\n".join(text.splitlines()[-8:])}
        if key == "validate":
            for name, rx in _VALIDATE_COUNTS:
                m = re.search(rx, text)
                res[name] = int(m.group(1)) if m else None
            # --folder scopes "Notes with problems"; missing/unregistered/orphans are vault-wide context
            blocks = problem_blocks(text)
            ours, pre = {}, {}
            for k, v in blocks.items():
                if k not in mine:
                    continue
                fresh = new_problems(v, baseline.get(k)) if k in baseline else (v or ["(problem)"])
                if fresh:
                    ours[k] = fresh
                old_keys = {_problem_key(b) for b in baseline.get(k) or []}
                old = [x for x in v if _problem_key(x) in old_keys]
                if old:
                    pre[k] = old
            res["problems_this_run"] = sum(len(v) for v in ours.values())
            res["this_run"] = [f"{k}: {'; '.join(v)}" for k, v in ours.items()]
            # notes whose problems aren't this run's: untouched notes, and touched shared notes whose only
            # problems were already there before this run
            res["elsewhere"] = len([k for k in blocks if k not in ours])
            res["pre_existing"] = [f"{k}: {'; '.join(v)}" for k, v in pre.items()]
            if res["problems"] is None:
                res["ok"] = False                       # the validator didn't finish: never claim a pass
            else:
                # a problem count with no note blocks can't be attributed: then it isn't a pass either
                res["ok"] = not ours and not (res["problems"] > 0 and not blocks)
            if ours:
                res["tail"] = "\n".join(res["this_run"][:8]) + "\n" + res["tail"].splitlines()[-1]
        out[key] = res
    return out


# ---------------------------------------------------------------- main

def _parse_crop(s):
    try:
        v = [int(x) for x in s.split(",")]
        if len(v) != 4 or v[2] <= 0 or v[3] <= 0 or v[0] < 0 or v[1] < 0:
            raise ValueError
        return v
    except ValueError:
        raise argparse.ArgumentTypeError("--crop wants x,y,w,h in source pixels, e.g. 0,120,1920,840")


def _parse_trim_arg(s):
    try:
        return animlib.parse_trim(s)
    except animlib.BadTrim as e:
        raise argparse.ArgumentTypeError(str(e))


def _err(it, e, **extra):
    """An error result for one input file: reason text and its machine code."""
    d = {"id": None, "kind": "error", "file": str(it["path"]), "code": animlib.error_code(e),
         "reason": str(e) if isinstance(e, animlib.AnimError) else f"{type(e).__name__}: {e}",
         "inbox_kept": it["in_inbox"]}
    d.update(extra)
    return d


def _result(rec, it, kept):
    return {"id": rec["id"], "kind": rec["kind"], "category": rec["category"], "title": rec["title"],
            "file": str(it["path"]), "card": rec.get("card"), "breakdown": rec.get("breakdown"),
            "media_dir": rec.get("media_dir"), "numbers": rec.get("numbers"),
            "numbers_brief": rec.get("numbers_brief"), "sheets": rec.get("sheets") or [],
            "frames": rec.get("analyst_frames") or [], "user_note": rec.get("note"), "scale": rec["scale"],
            "provenance": rec["provenance"], "provenance_guess": rec.get("provenance_guess"),
            "rig": rec["rig"], "spec_dir": rec.get("spec_dir"),
            "spec": rec.get("spec"), "scan": rec.get("scan"), "decode": rec.get("decode"),
            "trim": rec.get("trim"), "quarantine": rec.get("quarantine"), "inbox_kept": bool(kept), "reason": ("filed; couldn't delete from the inbox: " + ", ".join(kept))
            if kept else None}


def main_refile(ctx, a, cat_arg, emit):
    if not cat_arg:
        msg = "--refile needs --category"
        emit({"results": [], "tools": {}, "gpu": a.gpu_on, "error": msg}, [msg])
        return 2
    old_cat, _card = find_card(ctx, a.refile)
    if not old_cat:
        msg = f"no card {a.refile}.md in any Animation/<Cat>/ folder"
        emit({"results": [{"id": None, "kind": "error", "file": a.refile, "reason": msg}], "tools": {},
              "gpu": a.gpu_on, "dry_run": a.dry_run}, [msg])
        return 1
    if a.dry_run:
        new = animlib.next_id(ctx.vault, cat_arg)
        msg = f"would refile {a.refile} ({old_cat}) -> {new} ({cat_arg}); nothing written (dry run)"
        emit({"results": [{"id": new, "refiled_from": a.refile, "kind": "refile", "category": cat_arg,
                           "dry_run": True, "reason": None}], "tools": {}, "gpu": a.gpu_on, "dry_run": True}, [msg])
        return 0
    baseline = validate_baseline(ctx)
    try:
        rec = refile(ctx, a.refile, cat_arg)
    except Exception as e:
        msg = f"refile {a.refile}: {type(e).__name__}: {e} (rolled back)"
        emit({"results": [{"id": None, "kind": "error", "file": a.refile, "reason": msg}], "tools": {},
              "gpu": a.gpu_on, "dry_run": False}, [msg])
        return 1
    if baseline:
        # the refiled card and Breakdown carry their old problems over: those aren't new either
        for old, new in ((rec["file"], rec["card"]),
                         (str(ctx.bddir / f"Breakdown_{a.refile}.md"), rec.get("breakdown"))):
            try:
                ok_ = str(Path(old).resolve().relative_to(ctx.vault)).replace("\\", "/")
                nk_ = str(Path(new).resolve().relative_to(ctx.vault)).replace("\\", "/") if new else None
            except ValueError:
                continue
            if nk_ and ok_ in baseline:
                baseline[nk_] = [_id_rx(a.refile).sub(rec["id"], x) for x in baseline[ok_]]
    tools = run_tools(ctx, rec.pop("touched", []), baseline)
    emit({"results": [rec], "tools": tools, "gpu": a.gpu_on, "dry_run": False},
         [f"{rec['refiled_from']} -> {rec['id']} ({rec['category']})"])
    vt = tools.get("validate", {})
    return 3 if vt.get("ran") and not vt.get("ok") else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="File animation references into the vault (animsmith).")
    ap.add_argument("--vault", default=None, help="vault root (else ANIMSMITH_VAULT)")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--category", default=None, help="|".join(CATEGORIES))
    ap.add_argument("--rig", default="unknown", choices=["r6", "r15", "unknown", "R6", "R15"])
    ap.add_argument("--crop", type=_parse_crop, default=None, help="x,y,w,h in source pixels")
    ap.add_argument("--trim", type=_parse_trim_arg, default=None,
                    help="start-end seconds (e.g. 2.0-5.0): only that range is decoded and analysed")
    ap.add_argument("--provenance", choices=["own", "licensed", "third-party"], default=None,
                    help="override what the note implies (every file in the run; with --set-meta: the filed card)")
    ap.add_argument("--scale", choices=["absolute", "match"], default=None,
                    help="override what the note implies (every file in the run; with --set-meta: the filed card)")
    ap.add_argument("--pack", metavar="ID", default=None, help="print the per-reference block of a filed ID")
    ap.add_argument("--set-meta", metavar="ID", default=None,
                    help="rewrite a filed card's --provenance and/or --scale")
    ap.add_argument("--gpu", default="on", choices=["on", "off"])
    ap.add_argument("--refile", metavar="ID", default=None,
                    help="move a filed reference to --category (new ID; card, Breakdown, media, specs, hub line "
                         "and index row follow)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    a.gpu_on = a.gpu == "on"

    def emit(doc, human):
        if a.json:
            print(json.dumps(doc, indent=1, ensure_ascii=False))
        else:
            print("\n".join(human))

    try:
        vault = animlib.resolve_vault(a.vault)
    except SystemExit as e:
        emit({"results": [], "tools": {}, "gpu": a.gpu_on, "error": str(e)}, [str(e)])
        return 2
    ctx = Ctx(vault)
    cat_arg = None
    if a.category:
        cat_arg = animlib.category_of(a.category)
        if not cat_arg:
            msg = f"unknown --category '{a.category}' (use one of {', '.join(CATEGORIES)})"
            emit({"results": [], "tools": {}, "gpu": a.gpu_on, "error": msg}, [msg])
            return 2

    if a.refile:
        return main_refile(ctx, a, cat_arg, emit)
    if a.pack:
        try:
            block = pack_block(ctx, a.pack)
        except Exception as e:
            msg = f"pack {a.pack}: {e}"
            emit({"results": [{"id": None, "kind": "error", "file": a.pack, "reason": msg}], "tools": {},
                  "gpu": a.gpu_on, "error": msg}, [msg])
            return 1
        emit({"results": [block], "tools": {}, "gpu": a.gpu_on},
             [f"{k}: {v}" for k, v in block.items() if v not in (None, [], "")])
        return 0
    if a.set_meta:
        if not (a.provenance or a.scale):
            msg = "--set-meta needs --provenance and/or --scale"
            emit({"results": [], "tools": {}, "gpu": a.gpu_on, "error": msg}, [msg])
            return 2
        baseline = validate_baseline(ctx) if find_card(ctx, a.set_meta)[0] else None
        try:
            touched = set_meta(ctx, a.set_meta, a.provenance, a.scale)
            block = pack_block(ctx, a.set_meta)
        except Exception as e:
            msg = f"set-meta {a.set_meta}: {e} (nothing changed)"
            emit({"results": [{"id": None, "kind": "error", "file": a.set_meta, "reason": msg}], "tools": {},
                  "gpu": a.gpu_on, "error": msg}, [msg])
            return 1
        block["changed"] = touched
        tools = run_tools(ctx, touched, baseline) if touched else {}
        emit({"results": [block], "tools": tools, "gpu": a.gpu_on},
             [f"{a.set_meta}: provenance {block['provenance']}, scale {block['scale']} "
              f"({len(touched)} file(s) changed)"])
        vt = tools.get("validate", {})
        return 3 if vt.get("ran") and not vt.get("ok") else 0

    items = gather(ctx, a.files)
    inbox_list = [str(p) for it in items for p in it["paths"]]
    tpl_problems = check_templates(ctx)
    results, human, warnings = [], [], []
    if not items:
        human.append(f"nothing to file ({ctx.inbox} is empty or missing)")
    if tpl_problems:
        msg = "; ".join(tpl_problems)
        emit({"results": [], "tools": {}, "gpu": a.gpu_on, "error": msg, "inbox": inbox_list,
              "dry_run": a.dry_run}, human + [f"error: {msg}"])
        return 2

    failed, gpu_fail = 0, None
    touched = []
    dry_counts = {}
    catalog = None
    gpu_state = None                 # dry run: (ok, reason) once a video that would decode on the GPU is seen
    baseline, baseline_taken = None, False   # validate problems in existing notes before this run wrote anything
    for n_it, it in enumerate(items):
        name = it["path"].name
        if gpu_fail:
            results.append({"id": None, "kind": "skip", "file": str(it["path"]),
                            "reason": "not run: GPU failed earlier in this run", "inbox_kept": it["in_inbox"]})
            continue
        if it["kind"] == "skip":
            results.append({"id": None, "kind": "skip", "file": str(it["path"]), "reason": it["reason"],
                            "inbox_kept": it["in_inbox"]})
            human.append(f"skip  {name}: {it['reason']}")
            continue
        note = read_note(it["note_path"])
        try:
            note_trim = trim_of(note)
        except animlib.BadTrim as e:
            failed += 1
            results.append(_err(it, e, user_note=note))
            human.append(f"FAIL  {name}: {e} (fix the trim line in its note)")
            continue
        ncat, ntitle = note_category_title(note)
        cat = cat_arg or it["folder_cat"] or ncat
        if not cat:
            results.append({"id": None, "kind": "skip", "file": str(it["path"]), "reason": "no category",
                            "user_note": note, "inbox_kept": it["in_inbox"]})
            human.append(f"skip  {name}: no category (pass --category, use _inbox/anim/<cat>/, or start the note "
                         f"with the category)")
            continue
        stem = SET_RX.match(it["path"].stem).group(1) if len(it["paths"]) > 1 else it["path"].stem
        title = ntitle or _clean_title(stem)
        data = None
        if it["kind"] == "roblox":
            catalog = catalog or load_catalog()
            if catalog is None:
                results.append({"id": None, "kind": "skip", "file": str(it["path"]),
                                "reason": "anim_catalog missing", "inbox_kept": it["in_inbox"]})
                human.append(f"skip  {name}: anim_catalog missing")
                continue
            try:
                data = catalog.extract(str(it["path"]))
            except Exception as e:
                failed += 1
                results.append({"id": None, "kind": "error", "file": str(it["path"]), "code": "catalog_failed",
                                "reason": f"anim_catalog: {type(e).__name__}: {e}", "inbox_kept": it["in_inbox"]})
                human.append(f"FAIL  {name}: anim_catalog: {e}")
                continue
            if not data.get("sequences"):
                results.append({"id": None, "kind": "skip", "file": str(it["path"]),
                                "reason": "no KeyframeSequence in the file", "scan": data.get("scan"),
                                "inbox_kept": it["in_inbox"]})
                human.append(f"skip  {name}: no KeyframeSequence in the file")
                continue
        hub = ctx.hub(cat)
        hub_ok = hub.is_file() and HUB_END in hub.read_text(encoding="utf-8", errors="replace")
        if a.dry_run:
            count = len(data["sequences"]) if data else 1
            ids = []
            for _ in range(count):
                ids.append(animlib.next_id(ctx.vault, cat, skip=dry_counts.get(cat, 0)))
                dry_counts[cat] = dry_counts.get(cat, 0) + 1
            extra, probe_err, nvdec, gpu_bad = "", None, None, None
            trim = a.trim or note_trim
            if it["kind"] in ("video", "gif"):
                try:
                    pr = animlib.probe(it["path"])
                    extra = (f", {pr['duration']}s {pr['width']}x{pr['height']} @ {pr['fps']} ({pr['codec']}"
                             f"{' ' + pr['pix_fmt'] if pr.get('pix_fmt') else ''})")
                    if a.gpu_on and pr.get("codec") in animlib.NVDEC_CODECS:
                        ok, why = animlib.nvdec_format_ok(pr)
                        if not ok:
                            nvdec = f"nvdec_unsupported_format: {why} has no NVDEC decode on this GPU"
                            warnings.append(f"{name}: {nvdec}; filing it would fail (ask about a CPU decode)")
                        elif gpu_state is None:
                            # (critic r2) the dry run checks the GPU once, so it predicts a real run's exit 4
                            try:
                                animlib.gpu_check(True)
                                gpu_state = (True, None)
                            except GpuError as e:
                                gpu_state = (False, str(e))
                                warnings.append(f"GPU: {e}; a real run would stop with exit 4")
                        if not nvdec and gpu_state and not gpu_state[0]:
                            gpu_bad = gpu_state[1]
                except Exception as e:
                    probe_err = str(e)
                    extra = f", {probe_err}"
                    warnings.append(f"{name}: {probe_err}; filing it would fail")
            if not hub_ok:
                warnings.append(f"{hub.name}: missing or has no {HUB_END} marker; filing {name} would fail")
            prov, scale, guess = meta_of(note, a)
            if guess == "ambiguous":
                warnings.append(f"{name}: the note's provenance is unclear (would file as third-party + absolute); "
                                f"ask the user")
            results.append({"id": ids[0], "ids": ids, "kind": it["kind"], "category": cat, "title": title,
                            "file": str(it["path"]), "files": [str(p) for p in it["paths"]], "dry_run": True,
                            "user_note": note, "scale": scale, "provenance": prov, "provenance_guess": guess,
                            "trim": trim, "inbox_kept": it["in_inbox"],
                            "would_fail": bool(probe_err or nvdec or gpu_bad or not hub_ok),
                            "code": ("probe_failed" if probe_err else "nvdec_unsupported_format" if nvdec
                                     else "gpu_failed" if gpu_bad else None),
                            "reason": probe_err or nvdec or gpu_bad})
            human.append(f"would file {name} -> {', '.join(ids)} ({it['kind']}, {cat}{extra}"
                         + (f", note {it['note_path'].name}" if it["note_path"] else "") + "); "
                         + ("then delete it from the inbox" if it["in_inbox"] else "outside the inbox: copied"))
            continue
        if not baseline_taken:
            baseline, baseline_taken = validate_baseline(ctx), True
        undo = Undo(ctx)
        try:
            if it["kind"] == "roblox":
                recs = process_roblox(ctx, it, cat, note, title, a, undo, data)
            else:
                recs = process_media(ctx, it, cat, note, title, a, undo)
            _post_success_hook(ctx, recs)
        except GpuError as e:
            undo.rollback()
            gpu_fail = str(e)
            results.append(_err(it, e))
            human.append(f"STOP  {name}: {e} (rolled back; the rest of the inbox was not touched)")
            continue
        except Exception as e:
            undo.rollback()
            failed += 1
            results.append(_err(it, e))
            human.append(f"FAIL  {name}: {results[-1]['reason']} (rolled back; inbox left untouched)")
            continue
        except BaseException:
            # Ctrl+C or a forced exit: remove this file's half-made media and notes and the registry bump, then stop
            undo.rollback()
            raise
        for rec in recs:
            touched += [rec.get("card"), rec.get("breakdown"), str(ctx.hub(rec["category"])), str(ctx.index)]
        kept = delete_inbox(ctx, it) if it["in_inbox"] else []
        if recs and recs[0].get("provenance_guess") == "ambiguous":
            warnings.append(f"{name}: the note's provenance is unclear (filed as third-party + absolute); ask the "
                            f"user, then --set-meta {', '.join(r['id'] for r in recs)}")
        for rec in recs:
            results.append(_result(rec, it, kept))
            human.append(f"{rec['id']}  {rec['kind']} {rec['category']}  \"{rec['title']}\"  <- {name}"
                         + ("  [note]" if rec["note"] else ""))
        if kept:
            human.append(f"    filed, inbox copy kept (couldn't delete: {', '.join(kept)})")

    tools = {}
    wrote = any(r.get("card") for r in results)
    if wrote:
        tools = run_tools(ctx, [t for t in touched if t], baseline)
    elif a.dry_run:
        human.append("dry run: nothing written; a real run would then run build_mocs.py and validate_vault.py")
    validate_failed = bool(tools.get("validate", {}).get("ran")) and not tools["validate"].get("ok")
    doc = {"results": results, "tools": tools, "gpu": a.gpu_on, "dry_run": a.dry_run, "inbox": inbox_list,
           "warnings": warnings}
    if a.dry_run:
        # null: nothing in this run would decode on the GPU (or --gpu off), so nothing was checked
        doc["gpu_ok"] = gpu_state[0] if gpu_state else None
        doc["gpu_reason"] = gpu_state[1] if gpu_state else (
            "not checked: --gpu off" if not a.gpu_on else "not checked: no video would decode on the GPU")
    if gpu_fail:
        doc["error"] = gpu_fail
    for w in warnings:
        human.append(f"warning: {w}")
    for key, res in tools.items():
        head = "skipped" if not res["ran"] else f"exit {res['exit']}"
        if key == "validate" and res["ran"]:
            head += ", OK" if res["ok"] else ", PROBLEMS"
        human.append(f"--- {key}: {head}\n{res['tail']}")
    emit(doc, human)
    if gpu_fail:
        return 4
    if failed:
        return 1
    if validate_failed:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
