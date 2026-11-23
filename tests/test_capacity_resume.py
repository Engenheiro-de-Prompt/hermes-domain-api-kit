"""Authenticated capacity contract through the real client, entirely in memory."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from api_client import RelayClient, ClientError
from private_checkpoint import Journal


@contextlib.contextmanager
def endpoint(proof=True, no_store=True, *, status=429, remote=True, deleted=True,
             retry_after=1, privacy=True, overrides=None):
    error: dict[str, object] = {'type': 'capacity_busy'}
    if proof:
        error.update(admission='not_started', limit_scope='concurrency', retry_after=retry_after)
    error.update(overrides or {})
    response = MagicMock()
    response.status = status
    response.read.return_value = json.dumps({'error': error}).encode()
    headers = {'Cache-Control': 'no-store' if no_store else '',
               'X-Relay-Content-Deleted': 'true' if deleted else ''}
    response.getheader.side_effect = headers.get
    conn = MagicMock()
    conn.getresponse.return_value = response
    with patch('api_client.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
         patch('api_client.socket.socket'), patch('api_client.ssl.create_default_context'), \
         patch('api_client.http.client.HTTPConnection', return_value=conn):
        client = RelayClient('https://example.invalid/v1' if remote else 'http://127.0.0.1/v1',
                             'synthetic-client', require_privacy=privacy)
        yield client, conn


class CapacityResumeTests(unittest.TestCase):
    def test_only_proven_https_privacy_confirmed_rejection_has_retryable_code(self):
        cases = [({}, 'capacity_busy'), ({'proof': False}, 'http_429'),
                 ({'no_store': False}, 'http_429'), ({'deleted': False}, 'http_429'),
                 ({'remote': False}, 'http_429'), ({'privacy': False}, 'http_429'),
                 ({'status': 503}, 'http_503'), ({'retry_after': 0}, 'http_429'),
                 ({'retry_after': 61}, 'http_429'), ({'retry_after': True}, 'http_429'),
                 ({'retry_after': '1'}, 'http_429'),
                 ({'overrides': {'admission': 'started'}}, 'http_429'),
                 ({'overrides': {'limit_scope': 'quota'}}, 'http_429'),
                 ({'overrides': {'type': 'other'}}, 'http_429')]
        for options, code in cases:
            with self.subTest(options=options), endpoint(**options) as (client, conn):
                with self.assertRaises(ClientError) as error:
                    client.classify('synthetic', 'synthetic', {})
                self.assertEqual(error.exception.code, code)
                self.assertEqual(conn.request.call_count, 1)
                self.assertEqual(client.privacy_failure,
                                 None if code == 'capacity_busy' or not client.require_privacy else code)

    def test_resume_preserves_known_decisions_and_retries_only_proven_not_started(self):
        with tempfile.TemporaryDirectory() as tmp, endpoint() as (client, conn):
            path = Path(tmp).resolve() / 'journal'
            contract = {'synthetic': 'contract'}
            identities = ['one', 'two', 'three']; allowed = [{'ok': 'ok'}] * 3
            j = Journal(path, False, contract, identities, allowed)
            try:
                self.assertEqual(j.decision(lambda: 'ok', allowed[0]), 'ok')
                self.assertIsNone(j.decision(lambda: client.classify('synthetic', 'synthetic', {}), allowed[1]))
                self.assertEqual(j.failure_code, 'capacity_busy')
                self.assertTrue(j.paused)
                self.assertEqual([r['status'] for r in j.data['segments']], ['ok', 'pending', 'pending'])
                self.assertIsNone(j.decision(lambda: self.fail('must pause'), allowed[2]))
            finally:
                j.close()
            j = Journal(path, True, contract, identities, allowed)
            try:
                self.assertFalse(j.paused)
                self.assertEqual(j.decision(lambda: self.fail('must not replay'), allowed[0]), 'ok')
                self.assertEqual(j.decision(lambda: 'ok', allowed[1]), 'ok')
                self.assertEqual(j.decision(lambda: 'ok', allowed[2]), 'ok')
                self.assertEqual(conn.request.call_count, 1)
            finally:
                j.close()

    def test_bare_capacity_code_does_not_authorize_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = (Path(tmp).resolve() / 'journal', False, {}, ['one'], [{'ok': 'ok'}])
            j = Journal(*args)
            try:
                def unproven():
                    raise ClientError('capacity_busy')
                self.assertIsNone(j.decision(unproven, {'ok': 'ok'}))
                self.assertEqual(j.data['segments'][0]['status'], 'unknown')
            finally:
                j.close()


if __name__ == '__main__':
    unittest.main()
