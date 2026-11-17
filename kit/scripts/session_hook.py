"""animsmith SessionStart hook.

Prints a short status block: the vault path (from ANIMSMITH_VAULT), the reference cards per category, how many
Breakdowns wait for the analyst or the user (breakdown_status not-started / in-progress), how many files wait in the
inbox (11_ASSET_LIBRARY/_inbox/anim/**), and any build waiting at "final-pending-writeup" (approved, approval
write-up not done) or paused (ledger 11_ASSET_LIBRARY/Animation/ledger.jsonl, which may not exist yet).

Python 3, standard library only. It never fails: every error is swallowed and it always exits 0, so a broken vault
or ledger can't block a session. It only reads; ledger.py writes the ledger.
"""

import json
import os
import re
import sys

LIB = "11_ASSET_LIBRARY"
LEDGER_REL = (LIB, "Animation", "ledger.jsonl")
INBOX_REL = (LIB, "_inbox", "anim")
# category -> (card folder under 11_ASSET_LIBRARY, id prefix). Same table as animlib.CATEGORIES; kept here so the
# hook stays standard-library only and works even when another script is broken.
CATEGORIES = (
    ("combat", ("Animation", "Combat"), "ANIM-COMBAT-"),
    ("weapon", ("Animation", "Weapon"), "ANIM-WEAPON-"),
    ("ability", ("Animation", "Ability"), "ANIM-ABILITY-"),
    ("reaction", ("Animation", "Reaction"), "ANIM-REACTION-"),
    ("loco", ("Animation", "Locomotion"), "ANIM-LOCO-"),
    ("world", ("Animation", "World"), "ANIM-WORLD-"),
    ("camera", ("Animation", "Camera"), "ANIM-CAMERA-"),
)
PENDING = "final-pending-writeup"
PAUSED = "paused"
NOT_DONE = ("not-started", "in-progress")
SIDECAR_EXT = (".txt", ".md")
# The inbox may hold its own instructions note (README.md); it is not a reference or a sidecar.
IGNORED = ("desktop.ini", "thumbs.db", ".ds_store", ".gitkeep", "readme.md", "readme.txt")
STATUS_RE = re.compile(r"^breakdown_status:\s*([A-Za-z-]+)", re.M)
MAX_LISTED = 8


def _out(line):
    try:
        sys.stdout.write(line + "\n")
    except Exception:
        try:
            sys.stdout.write(line.encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:
            pass


def _listing(ids):
    shown = ", ".join(ids[:MAX_LISTED])
    if len(ids) > MAX_LISTED:
        shown += " (+%d more)" % (len(ids) - MAX_LISTED)
    return shown


def _front(path):
    """The frontmatter block of a card (or its first 4 KB): enough to read breakdown_status."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except Exception:
        return ""
    if head.startswith("---"):
        end = head.find("\n---", 3)
        if end > 0:
            return head[:end]
    return head


def cards(vault):
    """{cat: (count, [pending ids])}; folders that don't exist count as 0."""
    result = {}
    for cat, folder, prefix in CATEGORIES:
        path = os.path.join(vault, LIB, *folder)
        count, pending = 0, []
        try:
            names = sorted(os.listdir(path)) if os.path.isdir(path) else []
        except Exception:
            names = []
        for name in names:
            if not (name.startswith(prefix) and name.endswith(".md")):
                continue
            count += 1
            match = STATUS_RE.search(_front(os.path.join(path, name)))
            if match and match.group(1) in NOT_DONE:
                pending.append(name[:-3])
        result[cat] = (count, pending)
    return result


def inbox(vault):
    """(reference files, sidecar notes) anywhere under _inbox/anim/."""
    root = os.path.join(vault, *INBOX_REL)
    refs = notes = 0
    if not os.path.isdir(root):
        return refs, notes
    for _dir, _subdirs, files in os.walk(root):
        for name in files:
            low = name.lower()
            if low in IGNORED or low.startswith("."):
                continue
            if low.endswith(SIDECAR_EXT):
                notes += 1
            else:
                refs += 1
    return refs, notes


def ledger_rows(vault):
    """The last row per build id (ledger.py appends a full row per change)."""
    path = os.path.join(vault, *LEDGER_REL)
    latest = {}
    if not os.path.isfile(path):
        return latest
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            bid = row.get("id")
            key = bid if isinstance(bid, str) and bid else "(line %d)" % (n + 1)
            latest.pop(key, None)
            latest[key] = row
    return latest


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    vault = (os.environ.get("ANIMSMITH_VAULT") or "").strip().strip('"')
    if not vault:
        _out("animsmith: ANIMSMITH_VAULT is not set; /anim can't run (set it under env in ~/.claude/settings.json).")
        return
    if not os.path.isdir(vault):
        _out("animsmith: ANIMSMITH_VAULT folder not found: " + vault)
        return
    # A path one level off (e.g. a subfolder of the vault) would read as "0 cards" and hide pending work.
    if not os.path.isdir(os.path.join(vault, LIB)):
        _out("animsmith: ANIMSMITH_VAULT has no " + LIB + " folder; set it to the vault root "
             "(the folder that holds " + LIB + "): " + vault)
        return

    _out("animsmith: vault " + vault)

    try:
        per_cat = cards(vault)
        total = sum(count for count, _ in per_cat.values())
        parts = ["%s %d" % (cat, count) for cat, (count, _) in per_cat.items() if count]
        _out("animsmith: %d reference card%s%s" % (total, "" if total == 1 else "s",
                                                   (" (" + ", ".join(parts) + ")") if parts else ""))
        pending = [i for _, (_, ids) in per_cat.items() for i in ids]
        if pending:
            _out("animsmith: %d Breakdown%s not accepted yet (/anim learn picks them up): %s"
                 % (len(pending), "" if len(pending) == 1 else "s", _listing(pending)))
    except Exception:
        pass

    try:
        refs, notes = inbox(vault)
        if refs or notes:
            _out("animsmith: inbox %d file%s waiting (+%d note%s); run /anim learn"
                 % (refs, "" if refs == 1 else "s", notes, "" if notes == 1 else "s"))
    except Exception:
        pass

    try:
        rows = ledger_rows(vault)
    except Exception:
        rows = {}
    _out("animsmith: ledger %d build%s" % (len(rows), "" if len(rows) == 1 else "s"))
    waiting = [k for k, r in rows.items() if r.get("status") == PENDING]
    if waiting:
        _out("animsmith: approval write-up pending (" + PENDING + "): " + _listing(waiting))
    paused = [k for k, r in rows.items() if r.get("status") == PAUSED]
    if paused:
        _out("animsmith: paused builds: " + _listing(paused))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)
