import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[1] / 'session_hook.py'

CARD = """---
tags:
  - roblox-dev
category: {cat}
breakdown_status: {status}   # not-started | in-progress | done
status: draft
---

# {id}

breakdown_status: not-started (body text must not count)
"""


class SessionHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='anim hook ')
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / 'My Vault'
        self.lib = self.vault / '11_ASSET_LIBRARY'
        self.lib.mkdir(parents=True)

    def run_hook(self, vault):
        env = dict(os.environ)
        env['ANIMSMITH_VAULT'] = '' if vault is None else str(vault)
        proc = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=env,
                              encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        return proc.stdout

    def card(self, folder, card_id, status, cat='combat'):
        path = self.lib / 'Animation' / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / (card_id + '.md')).write_text(CARD.format(cat=cat, status=status, id=card_id), encoding='utf-8')

    def test_unset_missing_and_wrong_vault(self):
        self.assertIn('ANIMSMITH_VAULT is not set', self.run_hook(None))
        self.assertIn('folder not found', self.run_hook(self.vault / 'nope'))
        self.assertIn('has no 11_ASSET_LIBRARY', self.run_hook(self.lib))
        self.assertIn('vault ' + str(self.vault), self.run_hook('"%s"' % self.vault))

    def test_empty_vault(self):
        (self.lib / '_inbox' / 'anim').mkdir(parents=True)
        (self.lib / '_inbox' / 'anim' / 'README.md').write_text('how to use the inbox', encoding='utf-8')
        out = self.run_hook(self.vault)
        self.assertIn('0 reference cards', out)
        self.assertIn('ledger 0 builds', out)
        self.assertNotIn('inbox', out)
        self.assertNotIn('not accepted', out)

    def test_cards_pending_inbox_and_ledger(self):
        self.card('Combat', 'ANIM-COMBAT-0001', 'in-progress')
        self.card('Combat', 'ANIM-COMBAT-0002', 'done')
        self.card('Reaction', 'ANIM-REACTION-0001', 'not-started', 'reaction')
        self.card('Locomotion', 'ANIM-LOCO-0001', 'done', 'loco')
        (self.lib / 'Animation' / 'Combat' / 'notes.md').write_text('not a card', encoding='utf-8')
        inbox = self.lib / '_inbox' / 'anim'
        (inbox / 'weapon').mkdir(parents=True)
        (inbox / 'clip one.mp4').write_bytes(b'x')
        (inbox / 'clip one.mp4.txt').write_text('combat my words', encoding='utf-8')
        (inbox / 'weapon' / 'bolt.gif').write_bytes(b'x')
        (inbox / 'desktop.ini').write_text('', encoding='utf-8')
        (inbox / 'README.md').write_text('how to use the inbox', encoding='utf-8')
        ledger = self.lib / 'Animation' / 'ledger.jsonl'
        ledger.write_text('\n'.join([
            '{"id":"ANIM-BUILD-0001","status":"open"}',
            '{"id":"ANIM-BUILD-0001","status":"final-pending-writeup"}',
            '{"id":"ANIM-BUILD-0002","status":"paused"}',
            'not json',
        ]) + '\n', encoding='utf-8')
        out = self.run_hook(self.vault)
        self.assertIn('4 reference cards (combat 2, reaction 1, loco 1)', out)
        self.assertIn('2 Breakdowns not accepted yet', out)
        self.assertIn('ANIM-COMBAT-0001', out)
        self.assertIn('ANIM-REACTION-0001', out)
        self.assertNotIn('ANIM-COMBAT-0002', out)
        self.assertIn('inbox 2 files waiting (+1 note)', out)
        self.assertIn('ledger 2 builds', out)
        self.assertIn('final-pending-writeup): ANIM-BUILD-0001', out)
        self.assertIn('paused builds: ANIM-BUILD-0002', out)

    def test_unreadable_ledger_still_exits_zero(self):
        (self.lib / 'Animation' / 'ledger.jsonl').mkdir(parents=True)  # a folder where the file should be
        out = self.run_hook(self.vault)
        self.assertIn('ledger 0 builds', out)


if __name__ == '__main__':
    unittest.main()
