import unittest
from tools.check_publication import inspect


class PublicationTests(unittest.TestCase):
    def test_staged_symlink_is_refused_without_following_it(self):
        import contextlib, io, os, subprocess, tempfile
        from pathlib import Path
        from unittest.mock import patch
        import tools.check_publication as gate
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            oid = subprocess.check_output(['git', '-C', str(root), 'hash-object', '-w', '--stdin'], input=b'not-a-real-target').decode().strip()
            subprocess.run(['git', '-C', str(root), 'update-index', '--add', '--cacheinfo', '120000,' + oid + ',linked.py'], check=True)
            with patch.object(gate, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(gate.main(['--staged']), 1)
            self.assertIn('symlink', out.getvalue())

    def test_utf8_nul_is_binary_not_public_source(self):
        self.assertIn((0, 'unexpected_binary'), inspect('examples/renamed-source.py', b'content\x00hidden'))

    def test_tokens_locations_only(self):
        fake = 'g' + 'hp_' + 'S' * 40
        findings = inspect('helper.py', ('header\n' + fake).encode())
        self.assertIn((2, 'token'), findings)
        self.assertNotIn(fake, str(findings))

    def test_raw_artifact_and_donor_path_fail(self):
        self.assertIn((0, 'private_artifact_name'), inspect('nested/snapshot.json', b'{}'))
        path = '/home/' + 'virtualis' + '/private'
        self.assertIn((1, 'donor_path'), inspect('docs/demo.md', path.encode()))
        self.assertEqual(inspect('docs/demo.md', b'/caminho/do/perfil-autorizado'), [])

    def test_synthetic_contract_is_allowed(self):
        self.assertEqual(inspect('examples/demo.synthetic.json', b'{"source_id":"synthetic"}'), [])
        self.assertEqual(inspect('rubrics/domain.json', b'{"version":1}'), [])


if __name__ == '__main__':
    unittest.main()
