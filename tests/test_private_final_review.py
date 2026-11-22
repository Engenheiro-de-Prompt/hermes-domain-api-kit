import http.client
from pathlib import Path
import re
import socket
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import cli
from api_client import RelayClient, ClientError
from private_pipeline import _destination


class FinalReviewRegressions(unittest.TestCase):
    def test_all_deadline_timeouts_are_sticky_before_send_and_after_read(self):
        for phase in ('before_send', 'after_read'):
            with self.subTest(phase=phase):
                clock = types.SimpleNamespace(now=0)
                connection = Mock()
                response = Mock(status=200)
                response.getheader.side_effect = {'Cache-Control': 'no-store'}.get
                def address(*args, **kwargs):
                    if phase == 'before_send': clock.now = 100
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 1))]
                def read(*args):
                    clock.now = 100
                    return b'{"data":[]}'
                response.read.side_effect = read
                connection.getresponse.return_value = response
                client = RelayClient('http://127.0.0.1:1/v1', 'synthetic', timeout=1, require_privacy=True)
                with patch('api_client.time', types.SimpleNamespace(monotonic=lambda: clock.now)), patch('api_client.socket.getaddrinfo', side_effect=address) as dns, patch('api_client.socket.socket'), patch('api_client.http.client.HTTPConnection', return_value=connection):
                    with self.assertRaisesRegex(ClientError, '^timeout$'): client.models()
                    self.assertEqual(client.privacy_failure, 'timeout')
                    requests = connection.request.call_count
                    with self.assertRaisesRegex(ClientError, '^timeout$'): client.models()
                    self.assertEqual(connection.request.call_count, requests)
                    self.assertEqual(dns.call_count, 1)
                self.assertEqual(requests, 0 if phase == 'before_send' else 1)

    def test_equivalent_dotdot_destinations_cannot_escape_boundaries(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); home = root / 'profile'; home.mkdir()
            neutral = root / 'neutral'; neutral.mkdir()
            pairs = [(home, neutral / '..' / 'profile' / 'aggregate'),
                     (home, repo.parent / 'nonexistent-parent' / '..' / repo.name / 'aggregate'),
                     (neutral / '..' / 'profile', home / 'aggregate')]
            for selected, output in pairs:
                with self.subTest(selected=str(selected), output=str(output)):
                    args = cli.parser().parse_args(['private-analyze', '--home', str(selected), '--work', str(output)])
                    with self.assertRaisesRegex(ValueError, 'invalid_work|work_must_be_outside_repository'):
                        _destination(args)
                    self.assertFalse(output.exists())

    def test_workflow_steps_are_siblings_and_each_is_executable(self):
        lines = (Path(__file__).resolve().parents[1] / '.github/workflows/tests.yml').read_text().splitlines()
        step_headers = [(i, line) for i, line in enumerate(lines) if re.match(r'^\s*- (?:name|uses):', line)]
        self.assertTrue(step_headers)
        for index, (start, header) in enumerate(step_headers):
            self.assertTrue(header.startswith('      - ') and not header.startswith('       '), header)
            end = step_headers[index + 1][0] if index + 1 < len(step_headers) else len(lines)
            self.assertTrue('uses:' in header or any(line.startswith('        run:') for line in lines[start:end]), header)
        source = '\n'.join(lines)
        self.assertIn('python -B tools/check_publication.py', source)
        self.assertIn('python -B -m unittest discover -s tests -q', source)


if __name__ == '__main__':
    unittest.main()
