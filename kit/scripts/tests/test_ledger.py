import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='anim vault ')
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / 'My Vault'
        (self.vault / '11_ASSET_LIBRARY').mkdir(parents=True)
        self.root = ledger.anim_root(self.vault)
        self.path = self.root / 'ledger.jsonl'

    def cli(self, *args, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = ledger.main(['--vault', str(self.vault), '--json', *args])
        self.assertEqual(result, code, err.getvalue())
        if code:
            self.assertIn('error:', err.getvalue())
            return None
        return json.loads(out.getvalue())

    def test_next_id_scans_rows_builds_and_specs(self):
        self.assertEqual(ledger.next_id(self.vault), 'ANIM-BUILD-0001')
        self.root.mkdir(parents=True)
        self.path.write_text('\n'.join(json.dumps(r) for r in [
            {'id': 'ANIM-BUILD-0007', 'status': 'open'}, {'id': 'ANIM-BUILD-0007', 'status': 'final'},
            {'id': 'ANIM-BUILD-0002', 'status': 'abandoned'}]), encoding='utf-8')
        self.assertEqual(ledger.next_id(self.vault), 'ANIM-BUILD-0008')
        (self.root / '_builds').mkdir()
        (self.root / '_builds' / 'ANIM-BUILD-0011_Build_Notes.md').touch()
        self.assertEqual(ledger.next_id(self.vault), 'ANIM-BUILD-0012')
        (self.root / '_specs' / 'ANIM-COMBAT-0099').mkdir(parents=True)
        self.assertEqual(ledger.next_id(self.vault), 'ANIM-BUILD-0012')
        self.assertEqual(self.cli('next-id'), {'id': 'ANIM-BUILD-0012'})

    def test_open_is_append_only_and_never_reuses(self):
        first = ledger.open_build(self.vault, 'ANIM-BUILD-0001', 'Sniper bolt cycle')
        self.assertEqual((first['status'], first['kind']), ('open', 'make'))
        before = self.path.read_bytes()
        ledger.open_build(self.vault, 'ANIM-BUILD-0002', 'Second')
        self.assertTrue(self.path.read_bytes().startswith(before))
        with self.assertRaisesRegex(ValueError, 'never reused'):
            ledger.open_build(self.vault, 'ANIM-BUILD-0001', 'Reuse')
        for bad in ('../ANIM-BUILD-0003', 'bad', 'ANIM-BUILD-1', 'UI-BUILD-0001'):
            with self.assertRaises(ValueError):
                ledger.open_build(self.vault, bad, 'Bad')
        with self.assertRaises(ValueError):
            ledger.open_build(self.vault, 'ANIM-BUILD-0003', '  ')
        self.assertEqual(ledger.next_id(self.vault), 'ANIM-BUILD-0003')
        self.assertFalse((self.root / '.ledger.lock').exists())

    def test_state_moves_append_and_last_row_wins(self):
        self.cli('open', 'ANIM-BUILD-0001', '--title', 'Door slam')
        self.cli('state', 'ANIM-BUILD-0001', 'final', code=2)
        row = self.cli('state', 'ANIM-BUILD-0001', 'paused')
        self.assertEqual(row['status'], 'paused')
        self.assertEqual(row['paused_at'], row['updated'])
        self.cli('state', 'ANIM-BUILD-0001', 'final-pending-writeup', code=2)
        self.assertIsNone(self.cli('state', 'ANIM-BUILD-0001', 'open')['paused_at'])
        self.cli('state', 'ANIM-BUILD-0001', 'final-pending-writeup')
        self.assertEqual(self.cli('state', 'ANIM-BUILD-0001', 'final')['status'], 'final')
        self.cli('state', 'ANIM-BUILD-0001', 'open', code=2)
        self.cli('state', 'ANIM-BUILD-0009', 'paused', code=2)
        self.assertEqual(len(ledger.history(self.root)), 5)
        self.assertEqual(self.cli('get', 'ANIM-BUILD-0001')['status'], 'final')
        self.assertEqual(self.cli('list', '--status', 'final')[0]['title'], 'Door slam')

    def test_pause_open(self):
        self.cli('open', 'ANIM-BUILD-0001', '--title', 'A')
        self.cli('open', 'ANIM-BUILD-0002', '--title', 'B')
        self.cli('state', 'ANIM-BUILD-0002', 'final-pending-writeup')
        changed = self.cli('pause-open')
        self.assertEqual([r['id'] for r in changed], ['ANIM-BUILD-0001'])
        self.assertEqual(self.cli('get', 'ANIM-BUILD-0001')['status'], 'paused')
        self.assertEqual(self.cli('get', 'ANIM-BUILD-0002')['status'], 'final-pending-writeup')
        self.assertEqual(self.cli('pause-open'), [])

    def test_pause_open_never_fails(self):
        # No ledger yet, an unset vault, a wrong vault and a corrupt ledger: all exit 0 and write nothing.
        self.assertEqual(self.cli('pause-open'), [])
        self.assertFalse(self.path.exists())
        with patch.dict(os.environ, {'ANIMSMITH_VAULT': ''}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ledger.main(['pause-open']), 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ledger.main(['--vault', str(self.vault / 'nope'), 'pause-open']), 0)
        self.root.mkdir(parents=True)
        self.path.write_text('{bad json}\n', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ledger.main(['--vault', str(self.vault), 'pause-open']), 0)
        self.assertIn('skipped', err.getvalue())
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{bad json}\n')

    def test_missing_newline_corrupt_ledger_and_bad_vault(self):
        self.root.mkdir(parents=True)
        self.path.write_text('{"id":"ANIM-BUILD-0001","status":"final"}', encoding='utf-8')
        ledger.open_build(self.vault, 'ANIM-BUILD-0002', 'Second')
        self.assertEqual(len(ledger.history(self.root)), 2)
        self.path.write_text('{bad json}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            ledger.next_id(self.vault)
        self.cli('next-id', code=2)
        with self.assertRaisesRegex(ValueError, '11_ASSET_LIBRARY'):
            ledger.anim_root(Path(self.temp.name))
        with self.assertRaisesRegex(ValueError, 'ANIMSMITH_VAULT'):
            ledger.anim_root('')


if __name__ == '__main__':
    unittest.main()
