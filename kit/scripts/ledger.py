"""animsmith build ledger: VAULT/11_ASSET_LIBRARY/Animation/ledger.jsonl.

Append-only: every change appends the build's full row, and the last line for an id wins (session_hook.py reads it
the same way). Standard library only. --vault defaults to ANIMSMITH_VAULT.

    ledger.py next-id                         print the next unused ANIM-BUILD-#### id
    ledger.py open ANIM-BUILD-0001 --title T  append an open row for a new build
    ledger.py state ANIM-BUILD-0001 paused    move a build (open -> paused | final-pending-writeup | abandoned;
                                              paused -> open | abandoned; final-pending-writeup -> final)
    ledger.py get ID | list [--status S]
    ledger.py pause-open                      SessionEnd hook: every open build becomes paused; never fails

The build loop that drives these moves arrives in phase 3; phases 0-1 only need the file to exist and the hooks.
Exit 0 ok, 2 error (pause-open always exits 0).
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

REL = Path('11_ASSET_LIBRARY') / 'Animation' / 'ledger.jsonl'
ID_FULL = re.compile(r'ANIM-BUILD-\d{4,}')
ID_ANY = re.compile(r'ANIM-BUILD-(\d{4,})(?!\d)')
STATUSES = ('open', 'paused', 'final-pending-writeup', 'final', 'abandoned')
MOVES = {'open': {'paused', 'final-pending-writeup', 'abandoned'},
         'paused': {'open', 'abandoned'},
         'final-pending-writeup': {'final'}}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def anim_root(vault):
    """VAULT/11_ASSET_LIBRARY/Animation; the vault must hold 11_ASSET_LIBRARY."""
    vault = (str(vault) if vault else '').strip().strip('"')
    if not vault:
        raise ValueError('--vault or ANIMSMITH_VAULT is required')
    root = Path(vault)
    if not root.is_dir() or not (root / '11_ASSET_LIBRARY').is_dir():
        raise ValueError('vault must be the folder that holds 11_ASSET_LIBRARY: ' + vault)
    return root / REL.parent


def history(root):
    """Every row in file order. A bad line stops everything: an unknown row could hide a used id."""
    path = Path(root) / REL.name
    if not path.exists():
        return []
    result = []
    for n, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not ID_FULL.fullmatch(str(row.get('id', ''))):
                raise ValueError('missing/invalid id')
        except (ValueError, TypeError) as exc:
            raise ValueError(f'ledger.jsonl line {n}: {exc}; fix the line by hand before writing') from exc
        result.append(row)
    return result


def latest(root):
    rows = {}
    for row in history(root):
        rows.pop(row['id'], None)
        rows[row['id']] = row
    return rows


def next_id(vault):
    root = anim_root(vault)
    numbers = [0]
    for row in history(root):
        numbers.append(int(ID_ANY.fullmatch(row['id']).group(1)))
    for sub in ('_builds', '_specs'):
        folder = root / sub
        if folder.is_dir():
            for path in folder.rglob('*'):
                numbers.extend(int(m.group(1)) for m in ID_ANY.finditer(path.name))
    return f'ANIM-BUILD-{max(numbers) + 1:04d}'


@contextmanager
def writer_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.ledger.lock'
    deadline = time.monotonic() + 5
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError('ledger writer lock is busy; retry (delete .ledger.lock if a writer crashed)')
            time.sleep(.05)
    try:
        os.close(fd)
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def append(root, rows):
    path = root / REL.name
    # Existing history may lack its final newline; never join two JSON rows.
    separator = ''
    if path.exists() and path.stat().st_size:
        with path.open('rb') as stream:
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b'\n':
                separator = '\n'
    text = ''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows)
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(separator + text)
        stream.flush()
        os.fsync(stream.fileno())


def open_build(vault, build_id, title, kind='make'):
    if not ID_FULL.fullmatch(build_id or ''):
        raise ValueError('id must be ANIM-BUILD-####')
    if not (title or '').strip() or not (kind or '').strip():
        raise ValueError('title and kind must be nonempty')
    root = anim_root(vault)
    with writer_lock(root):
        if build_id in latest(root):
            raise ValueError(f'{build_id} already has ledger history; ids are never reused')
        stamp = now()
        row = {'id': build_id, 'status': 'open', 'title': title.strip(), 'kind': kind.strip(),
               'created': stamp, 'updated': stamp, 'paused_at': None}
        append(root, [row])
    return row


def set_state(vault, build_id, status):
    if status not in STATUSES:
        raise ValueError('status must be one of ' + ', '.join(STATUSES))
    root = anim_root(vault)
    with writer_lock(root):
        rows = latest(root)
        if build_id not in rows:
            raise ValueError(f'build not found: {build_id}')
        row = dict(rows[build_id])
        if status not in MOVES.get(row.get('status'), set()):
            raise ValueError(f"{build_id}: cannot move {row.get('status')} -> {status}")
        stamp = now()
        row.update(status=status, updated=stamp)
        row['paused_at'] = stamp if status == 'paused' else None
        append(root, [row])
    return row


def pause_open(vault):
    """Every open build becomes paused. A missing vault or ledger is not an error (SessionEnd)."""
    vault = (str(vault) if vault else '').strip().strip('"')
    if not vault or not (Path(vault) / REL).is_file():
        return []
    root = anim_root(vault)
    with writer_lock(root):
        stamp = now()
        changed = []
        for row in latest(root).values():
            if row.get('status') == 'open':
                row = dict(row)
                row.update(status='paused', updated=stamp, paused_at=stamp)
                changed.append(row)
        if changed:
            append(root, changed)
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vault', default=os.environ.get('ANIMSMITH_VAULT'))
    ap.add_argument('--json', action='store_true')
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('next-id', help='print the next unused build id')
    op = sub.add_parser('open', help='append an open row for a new build')
    op.add_argument('id')
    op.add_argument('--title', required=True)
    op.add_argument('--kind', default='make')
    st = sub.add_parser('state', help='move a build to a new status')
    st.add_argument('id')
    st.add_argument('status', choices=STATUSES)
    gp = sub.add_parser('get', help='print one build')
    gp.add_argument('id')
    lp = sub.add_parser('list', help='list builds')
    lp.add_argument('--status', choices=STATUSES)
    sub.add_parser('pause-open', help='SessionEnd: mark every open build paused')
    a = ap.parse_args(argv)
    try:
        if a.command == 'pause-open':
            try:
                result = pause_open(a.vault)
            except (OSError, ValueError) as exc:
                print(f'animsmith ledger: pause-open skipped: {exc}', file=sys.stderr)
                return 0
        elif a.command == 'next-id':
            result = next_id(a.vault)
        elif a.command == 'open':
            result = open_build(a.vault, a.id, a.title, a.kind)
        elif a.command == 'state':
            result = set_state(a.vault, a.id, a.status)
        elif a.command == 'get':
            rows = latest(anim_root(a.vault))
            if a.id not in rows:
                raise ValueError(f'build not found: {a.id}')
            result = rows[a.id]
        else:
            result = [r for r in latest(anim_root(a.vault)).values() if not a.status or r.get('status') == a.status]
        if a.json:
            print(json.dumps(result if not isinstance(result, str) else {'id': result}, ensure_ascii=False))
        elif isinstance(result, str):
            print(result)
        elif isinstance(result, list):
            for row in result:
                print(f"{row['id']}  {row.get('status')}")
        else:
            print(f"{result['id']}  {result.get('status')}")
        return 0
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
